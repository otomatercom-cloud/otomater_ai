# -*- coding: utf-8 -*-
"""
Dynamic module/model discovery for Otomater AI (Phase 2).

This module builds an in-memory index of installed, usable business models
so the AI can be told "here is what you can operate on" without any
hardcoded list of modules. It deliberately does NOT hardcode model names -
everything is read from ir.model / ir.model.fields / ir.model.access at
runtime, so a brand new custom module (e.g. enq_management,
employee_incentive_wallet) becomes usable by the AI the moment it's
installed, with zero changes to otomater_ai itself.

Two cheap layers, two expensive layers:
  - get_installed_models()  -> cheap, cached per-registry (ormcache).
                                Just model/description, used to build the
                                shortlist for a given user message.
  - score_models()          -> cheap, in-memory token match, no DB hits.
  - get_model_schema()      -> heavier (fields_get + access checks), only
                                called for the handful of shortlisted models
                                actually sent to the LLM for one request.
  - get_model_access()      -> heavier, per-model ACL check for the
                                current user, also only called for the
                                shortlist.
"""

import re

from odoo import api, models, tools

# Technical/infrastructure prefixes that are never useful as an AI-operable
# "business" model. Extend this list rather than trying to allow-list every
# real business model - the whole point of this service is to need zero
# per-module changes.
EXCLUDED_PREFIXES = (
    "ir.",
    "base.",
    "base_import.",
    "bus.",
    "web_tour.",
    "web_editor.",
    "report.",
    "res.lang",
    "res.currency",
    "res.country",
    "res.bank",
    "sql_db",
    "workflow",
    "change.password",
    "res.config",
)

EXCLUDED_EXACT = {
    "res.currency.rate",
    "res.company",
}

_TOKEN_RE = re.compile(r"[a-zA-Z]+")


def _is_excluded(model_name):
    if model_name in EXCLUDED_EXACT:
        return True
    return any(model_name.startswith(p) for p in EXCLUDED_PREFIXES)


def _stem(token):
    """Tiny stemmer so 'lead' matches 'leads', 'students' matches 'student'."""
    t = token.lower()
    for suffix in ("ies", "es", "s"):
        if len(t) > 3 and t.endswith(suffix):
            return t[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return t


class AiIntrospection(models.AbstractModel):
    """Namespaced under a real (abstract) Odoo model so it participates in
    the registry cache lifecycle: @tools.ormcache is automatically
    invalidated whenever the registry reloads (module install/upgrade),
    which is exactly when the set of installed models can change."""

    _name = "ai.introspection"
    _description = "Otomater AI - Model/Module Introspection Service"

    @api.model
    @tools.ormcache()
    def get_installed_models(self):
        """Return [(model_name, description, transient), ...] for every
        model that is (a) not a technical/infra model and (b) has at least
        one ir.model.access record granting some group read access."""
        self.env.cr.execute(
            """
            SELECT DISTINCT m.id, m.model, m.transient
            FROM ir_model m
            WHERE EXISTS (
                SELECT 1 FROM ir_model_access a
                WHERE a.model_id = m.id AND a.perm_read = true
            )
            ORDER BY m.model
            """
        )
        rows = self.env.cr.fetchall()
        # `ir_model.name` is a translatable field - stored as a jsonb
        # {lang: value} dict when translations are active, not a plain
        # string. Reading it via raw SQL would leak that raw dict straight
        # into scoring/prompt text (score_models() ran re.findall() on it
        # and blew up with "expected string or bytes-like object, got
        # 'dict'"). So we only pull id/model/transient via SQL, and
        # resolve the human-readable name through the ORM, which always
        # returns the current-language string, translations or not.
        model_ids = [row[0] for row in rows if not _is_excluded(row[1])]
        records = self.env["ir.model"].browse(model_ids)
        by_id = {rec.id: (rec.name or "") for rec in records}
        return [
            (model, by_id.get(model_id, ""), transient)
            for model_id, model, transient in rows
            if not _is_excluded(model)
        ]

    @api.model
    def score_models(self, query, limit=8):
        """Very lightweight relevance scoring: token overlap between the
        user's message and each model's technical name + description.
        No DB access beyond the cached installed-models list - safe to call
        on every chat message."""
        query_tokens = set(_stem(t) for t in _TOKEN_RE.findall(query or ""))
        if not query_tokens:
            return []

        scored = []
        for model_name, description, transient in self.get_installed_models():
            if transient:
                continue
            haystack = set(
                _stem(t)
                for t in _TOKEN_RE.findall(model_name.replace(".", " ").replace("_", " "))
            ) | set(_stem(t) for t in _TOKEN_RE.findall(description or ""))
            overlap = len(query_tokens & haystack)
            if overlap:
                scored.append((overlap, model_name, description))

        scored.sort(key=lambda t: t[0], reverse=True)
        return [(m, d) for _, m, d in scored[:limit]]

    @api.model
    def get_model_access(self, model_name):
        """Access rights the CURRENT user actually has on model_name -
        never sudo'd, this must reflect real ACL/record-rule reality."""
        if model_name not in self.env:
            return {"read": False, "write": False, "create": False, "unlink": False}
        Model = self.env[model_name]
        access = {}
        for operation in ("read", "write", "create", "unlink"):
            try:
                access[operation] = Model.check_access_rights(operation, raise_exception=False)
            except Exception:
                access[operation] = False
        return access

    @api.model
    def get_model_schema(self, model_name, max_fields=40):
        """Compact field schema for prompt injection: name, label, type,
        relation (for relational fields), required. Capped at max_fields to
        keep prompts small - stored fields most likely to matter
        (Char/Many2one/Selection/Boolean/Date*) are prioritized over heavy
        computed/binary/html fields."""
        if model_name not in self.env:
            return {}
        Model = self.env[model_name]
        try:
            fields_data = Model.fields_get()
        except Exception:
            return {}

        priority_types = ("char", "many2one", "selection", "boolean", "date", "datetime", "integer", "float", "text")
        skip_types = ("binary", "html")
        skip_names = {"__last_update", "write_date", "write_uid", "create_uid", "display_name"}

        items = []
        for fname, fdef in fields_data.items():
            if fname in skip_names or fdef.get("type") in skip_types:
                continue
            items.append((fname, fdef))

        items.sort(key=lambda kv: (kv[1].get("type") not in priority_types, kv[0]))
        items = items[:max_fields]

        schema = {}
        for fname, fdef in items:
            entry = {
                "type": fdef.get("type"),
                "label": fdef.get("string"),
                "required": bool(fdef.get("required")),
            }
            if fdef.get("relation"):
                entry["relation"] = fdef["relation"]
            if fdef.get("selection") and isinstance(fdef.get("selection"), list):
                entry["options"] = [v for v, _ in fdef["selection"][:15]]
            schema[fname] = entry
        return schema

    @api.model
    def build_tool_context(self, query, limit=6, pinned_models=None):
        """Top-level entry point used by ai.conversation: given the user's
        message, return the shortlisted models with schema + access, ready
        to be serialized into the planning system prompt."""
        shortlist = self.score_models(query, limit=limit)
        # Models already used earlier in this conversation stay in context so
        # follow-ups like "which are they?" keep working.
        pinned = []
        for m in (pinned_models or []):
            if m and m in self.env and m not in [x[0] for x in pinned]:
                desc = dict((n, d) for n, d, _t in self.get_installed_models()).get(m, "")
                pinned.append((m, desc))
        pinned_names = {m for m, _d in pinned}
        shortlist = pinned + [x for x in shortlist if x[0] not in pinned_names]
        context = []
        for model_name, description in shortlist:
            access = self.get_model_access(model_name)
            if not access.get("read"):
                continue
            context.append(
                {
                    "model": model_name,
                    "description": description,
                    "access": access,
                    "fields": self.get_model_schema(model_name),
                }
            )
        return context
