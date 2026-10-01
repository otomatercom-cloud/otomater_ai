# -*- coding: utf-8 -*-
"""
Dynamic tool execution engine for Otomater AI (Phase 2).

Every function here executes strictly as `self.env.user` (never sudo) so
normal Odoo ACL and record rules are the ONLY thing standing between the
AI and the database - exactly as if the user had clicked the equivalent
button in the UI themselves. Nothing in this file bypasses security;
if a real access check would fail for the user, it fails here too and the
resulting AccessError is caught and reported back as a tool error.

Read-only tools (search_records, count_records, read_record, open_form,
download_report) execute immediately. Everything that mutates data
(create_record, update_record, delete_record, call_method,
execute_server_action) is routed through ai.pending.action for explicit
user confirmation before anything actually runs - see
DESTRUCTIVE_TOOLS below and ai_conversation.py / ai_pending_action.py.
"""

from odoo import api, models
from odoo.exceptions import AccessError, UserError, ValidationError

DESTRUCTIVE_TOOLS = {
    "create_record",
    "update_record",
    "delete_record",
    "call_method",
    "execute_server_action",
}

READ_ONLY_TOOLS = {
    "search_records",
    "count_records",
    "read_record",
    "open_form",
    "download_report",
    "search_knowledge",
}

ALL_TOOLS = DESTRUCTIVE_TOOLS | READ_ONLY_TOOLS

# Methods that must never be reachable through the generic call_method tool,
# regardless of what a model happens to name a public method - these are
# ORM/framework primitives, not business actions, and calling them via a
# free-form "method_name" string would sidestep the create/update/delete
# tools' own validation.
CALL_METHOD_BLACKLIST = {
    "write",
    "create",
    "unlink",
    "read",
    "search",
    "search_read",
    "search_count",
    "fields_get",
    "sudo",
    "with_user",
    "with_context",
    "with_env",
    "browse",
    "exists",
    "check_access_rights",
    "check_access_rule",
    "_compute_display_name",
}


class AiToolExecutor(models.AbstractModel):
    _name = "ai.tool.executor"
    _description = "Otomater AI - Dynamic Tool Execution Engine"

    # ---------------------------------------------------------------
    # Guards
    # ---------------------------------------------------------------
    def _assert_operable_model(self, model_name):
        installed = dict(
            (m, d) for m, d, _t in self.env["ai.introspection"].get_installed_models()
        )
        if model_name not in installed:
            raise UserError(
                "'%s' is not a model Otomater AI is allowed to operate on." % model_name
            )
        if model_name not in self.env:
            raise UserError("Model '%s' does not exist." % model_name)

    # ---------------------------------------------------------------
    # Read-only tools
    # ---------------------------------------------------------------
    @api.model
    def _normalize_domain(self, Model, domain):
        """Make AI-written domains robust: resolve 'today'/'yesterday' and
        date-only strings on datetime fields (create_date etc.) into a proper
        range in the USER's timezone, converted to UTC."""
        import json as _json
        from datetime import datetime, timedelta
        import pytz
        if isinstance(domain, str):
            try:
                domain = _json.loads(domain)
            except ValueError:
                return []
        tz = pytz.timezone(self.env.user.tz or "UTC")
        today = datetime.now(tz).date()

        def to_utc(d):
            return tz.localize(datetime(d.year, d.month, d.day)).astimezone(pytz.utc).replace(tzinfo=None)

        def parse_day(v):
            if not isinstance(v, str):
                return None
            v = v.strip().lower()
            if v in ("today", "now"):
                return today
            if v == "yesterday":
                return today - timedelta(days=1)
            if len(v) == 10:
                try:
                    return datetime.strptime(v, "%Y-%m-%d").date()
                except ValueError:
                    return None
            if len(v) >= 19 and v[10] in " T" and v[11:19] == "00:00:00":
                try:
                    return datetime.strptime(v[:10], "%Y-%m-%d").date()
                except ValueError:
                    return None
            return None

        fmt = "%Y-%m-%d %H:%M:%S"
        out = []
        for leaf in domain or []:
            if not (isinstance(leaf, (list, tuple)) and len(leaf) == 3):
                out.append(leaf)
                continue
            fname, op, val = leaf
            field = Model._fields.get(fname) if isinstance(fname, str) else None
            if field is None:
                out.append(leaf)
                continue
            day = parse_day(val)
            if field.type == "datetime" and day:
                start, end = to_utc(day), to_utc(day + timedelta(days=1))
                if op in ("=", "=="):
                    out += ["&", (fname, ">=", start.strftime(fmt)), (fname, "<", end.strftime(fmt))]
                elif op in (">=", ">") and op == ">=":
                    out.append((fname, ">=", start.strftime(fmt)))
                elif op == ">":
                    out.append((fname, ">=", end.strftime(fmt)))
                elif op == "<":
                    out.append((fname, "<", start.strftime(fmt)))
                elif op == "<=":
                    out.append((fname, "<", end.strftime(fmt)))
                else:
                    out.append(leaf)
            elif field.type == "date" and day:
                out.append((fname, op, day.strftime("%Y-%m-%d")))
            else:
                out.append(leaf)
        # '&' implicit between top-level leaves: our inserted '&' groups only the pair
        # when it sits at the front of a leaf, which is valid Polish notation.
        return out

    def search_records(self, model_name, domain=None, fields=None, limit=20, order=None):
        self._assert_operable_model(model_name)
        domain = self._normalize_domain(self.env[model_name], domain or [])
        limit = min(int(limit or 20), 100)
        Model = self.env[model_name]
        records = Model.search(domain, limit=limit, order=order or None)
        if fields:
            valid = [f for f in fields if f in Model._fields]
            data = records.read(valid) if valid else []
        else:
            default_fields = self._default_search_fields(Model)
            data = records.read(default_fields) if default_fields else []
            if not data:
                data = [{"id": r.id, "display_name": r.display_name} for r in records]
        return {"count": len(records), "records": data}

    @api.model
    def _default_search_fields(self, Model, max_fields=7):
        """When the AI doesn't name fields, return the most informative stored
        fields so results show real details (name/phone/stage...), not just IDs."""
        mapping = self.env["ai.model.mapping"].get_active_mappings().get(Model._name)
        if mapping and mapping.display_field_ids:
            mapped = [f.name for f in mapping.display_field_ids if f.name in Model._fields]
            if mapped:
                return mapped
        preferred = ("name", "phone", "mobile", "email", "email_from", "state", "stage_id",
                     "user_id", "partner_id", "date", "create_date")
        out = [f for f in preferred if f in Model._fields and Model._fields[f].store]
        for fname, f in Model._fields.items():
            if len(out) >= max_fields:
                break
            if fname in out or not f.store or f.type not in ("char", "selection", "many2one"):
                continue
            if fname.startswith(("write_", "create_", "__")) or fname in ("display_name",):
                continue
            out.append(fname)
        return out[:max_fields]

    def count_records(self, model_name, domain=None):
        self._assert_operable_model(model_name)
        domain = self._normalize_domain(self.env[model_name], domain or [])
        domain = domain or []
        return {"count": self.env[model_name].search_count(domain)}

    def read_record(self, model_name, res_id, fields=None):
        self._assert_operable_model(model_name)
        record = self.env[model_name].browse(int(res_id))
        record.check_access_rights("read")
        record.check_access_rule("read")
        if not record.exists():
            raise UserError("Record %s#%s does not exist." % (model_name, res_id))
        return record.read(fields)[0]

    def open_form(self, model_name, res_id):
        self._assert_operable_model(model_name)
        record = self.env[model_name].browse(int(res_id))
        if not record.exists():
            raise UserError("Record %s#%s does not exist." % (model_name, res_id))
        return {
            "type": "ir.actions.act_window",
            "res_model": model_name,
            "res_id": record.id,
            "views": [[False, "form"]],
            "target": "current",
        }

    def download_report(self, report_ref, res_ids):
        report = self.env.ref(report_ref, raise_if_not_found=False)
        if not report or report._name != "ir.actions.report":
            raise UserError("Report '%s' was not found." % report_ref)
        if report.groups_id and not (set(report.groups_id.ids) & set(self.env.user.groups_id.ids)):
            raise AccessError("You are not allowed to generate this report.")
        res_ids = res_ids if isinstance(res_ids, (list, tuple)) else [res_ids]
        return {
            "type": "ir.actions.report",
            "report_name": report.report_name,
            "report_type": report.report_type,
            "context": {"active_ids": res_ids},
        }

    def search_knowledge(self, query, limit=5):
        import json

        from .ai_knowledge_service import cosine_similarity

        limit = min(int(limit or 5), 20)
        provider = self.env["ai.provider"].get_default_embedding_provider(self.env.company.id)
        if not provider:
            raise UserError(
                "No embedding provider is configured, so the Knowledge Base can't "
                "be searched yet. Mark a provider 'Use for Embeddings' under AI "
                "Settings > Providers."
            )
        query_vector = provider.get_embedding([query])[0]

        chunks = self.env["ai.knowledge.chunk"].search(
            [("document_id.status", "=", "indexed"), ("document_id.active", "=", True)]
        )
        scored = []
        for chunk in chunks:
            try:
                vector = json.loads(chunk.embedding or "[]")
            except ValueError:
                continue
            score = cosine_similarity(query_vector, vector)
            if score > 0:
                scored.append((score, chunk))
        scored.sort(key=lambda t: t[0], reverse=True)

        results = [
            {
                "document": chunk.document_id.name,
                "document_id": chunk.document_id.id,
                "score": round(score, 4),
                "content": chunk.content[:800],
            }
            for score, chunk in scored[:limit]
        ]
        return {"results": results}

    # ---------------------------------------------------------------
    # Destructive tools - only ever invoked from ai.pending.action after
    # explicit user approval.
    # ---------------------------------------------------------------
    def create_record(self, model_name, values):
        self._assert_operable_model(model_name)
        record = self.env[model_name].create(values or {})
        return {"id": record.id, "display_name": record.display_name}

    def update_record(self, model_name, res_ids, values):
        self._assert_operable_model(model_name)
        res_ids = res_ids if isinstance(res_ids, (list, tuple)) else [res_ids]
        records = self.env[model_name].browse([int(i) for i in res_ids])
        if not records.exists():
            raise UserError("No matching %s record(s) found for %s." % (model_name, res_ids))
        records.write(values or {})
        return {"updated_ids": records.ids}

    def delete_record(self, model_name, res_ids):
        self._assert_operable_model(model_name)
        res_ids = res_ids if isinstance(res_ids, (list, tuple)) else [res_ids]
        records = self.env[model_name].browse([int(i) for i in res_ids])
        existing_ids = records.exists().ids
        records.unlink()
        return {"deleted_ids": existing_ids}

    def call_method(self, model_name, res_ids, method_name, args=None, kwargs=None):
        self._assert_operable_model(model_name)
        if not method_name or method_name.startswith("_") or method_name in CALL_METHOD_BLACKLIST:
            raise UserError("Calling method '%s' is not permitted." % method_name)
        Model = self.env[model_name]
        if not hasattr(Model, method_name):
            raise UserError("Method '%s' does not exist on %s." % (method_name, model_name))
        res_ids = res_ids if isinstance(res_ids, (list, tuple)) else [res_ids]
        records = Model.browse([int(i) for i in res_ids]) if res_ids else Model
        method = getattr(records, method_name)
        result = method(*(args or []), **(kwargs or {}))
        # Keep the audit trail / chat reply JSON-serializable.
        if isinstance(result, models.BaseModel):
            return {"result_ids": result.ids}
        if isinstance(result, (dict, list, str, int, float, bool)) or result is None:
            return {"result": result}
        return {"result": str(result)}

    def execute_server_action(self, action_id, res_ids=None):
        action = self.env["ir.actions.server"].browse(int(action_id))
        if not action.exists():
            raise UserError("Server action %s does not exist." % action_id)
        if action.groups_id and not (set(action.groups_id.ids) & set(self.env.user.groups_id.ids)):
            raise AccessError("You are not allowed to run this server action.")
        model_name = action.model_id.model
        self._assert_operable_model(model_name)
        records = self.env[model_name]
        if res_ids:
            res_ids = res_ids if isinstance(res_ids, (list, tuple)) else [res_ids]
            records = records.browse([int(i) for i in res_ids])
        result = action.with_context(active_model=model_name, active_ids=records.ids).run()
        return {"result": result if isinstance(result, (dict, type(None))) else str(result)}

    # ---------------------------------------------------------------
    # Dispatch
    # ---------------------------------------------------------------
    @api.model
    def execute_tool(self, tool_name, params):
        """Single entry point used by both the immediate (read-only) path
        in ai.conversation and the confirmed (destructive) path in
        ai.pending.action. Always returns a JSON-serializable dict with
        'ok' and either 'data' or 'error'."""
        params = params or {}
        if tool_name not in ALL_TOOLS:
            return {"ok": False, "error": "Unknown tool '%s'." % tool_name}
        try:
            method = getattr(self, tool_name)
            data = method(**params)
            return {"ok": True, "data": data}
        except (AccessError, UserError, ValidationError) as exc:
            return {"ok": False, "error": str(exc)}
        except TypeError as exc:
            return {"ok": False, "error": "Invalid parameters for %s: %s" % (tool_name, exc)}
        except Exception as exc:  # noqa: BLE001 - surfaced to the user/audit log, not swallowed
            return {"ok": False, "error": "Unexpected error: %s" % exc}
