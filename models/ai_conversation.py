# -*- coding: utf-8 -*-
import json
import logging

from odoo import api, fields, models, _

from .ai_tool_executor import DESTRUCTIVE_TOOLS, READ_ONLY_TOOLS

_logger = logging.getLogger(__name__)

PLANNER_SYSTEM_PROMPT = """You are Otomater AI, an assistant embedded inside an Odoo ERP system.
{persona_block}
You must respond with ONLY a single JSON object - no markdown fences, no prose before or
after it - matching exactly this shape:

{{
  "action": "chat" | "search_records" | "count_records" | "read_record" | "search_knowledge" |
            "create_record" | "update_record" | "delete_record" | "call_method" |
            "execute_server_action",
  "model": "<technical model name, e.g. res.partner> or null when action is chat/search_knowledge",
  "params": {{ ... tool-specific arguments, {{}} when action is chat }},
  "message": "<short natural-language reply to show the user right now>"
}}

Tool parameter shapes:
- search_records: {{"model_name": "...", "domain": [...], "fields": ["..."], "limit": 20}}
- count_records: {{"model_name": "...", "domain": [...]}}
- read_record: {{"model_name": "...", "res_id": 1, "fields": ["..."]}}
- search_knowledge: {{"query": "...", "limit": 5}} - use this for questions about company
  policies, FAQs, manuals, or any document that was uploaded to the Knowledge Base, rather
  than a database model.
- create_record: {{"model_name": "...", "values": {{...}}}}
- update_record: {{"model_name": "...", "res_ids": [1, 2], "values": {{...}}}}
- delete_record: {{"model_name": "...", "res_ids": [1]}}
- call_method: {{"model_name": "...", "res_ids": [1], "method_name": "...", "args": [], "kwargs": {{}}}}
- execute_server_action: {{"action_id": 1, "res_ids": [1]}}

Rules:
1. Only use a model from the "Available models" list below - never invent or guess a
   technical model name that isn't listed.
2. If nothing in "Available models" is relevant to the request, or the request is just
   conversation/a question you can answer directly, use action "chat" with model null and
   params {{}}. Put your answer in "message".
3. create_record / update_record / delete_record / call_method / execute_server_action are
   NEVER executed immediately - they always require the user to click Confirm first. Write
   "message" as a clear plain-language description of exactly what will happen if confirmed,
   e.g. "This will create a new Leave Request for John Doe from 2026-07-10 to 2026-07-12."
4. search_records / count_records / read_record run immediately - "message" should be a
   short framing sentence like "Here's what I found:" since the actual records are appended
   automatically after your message.
5. For search_records ALWAYS put useful "fields" in params (name, phone, mobile, email,
   stage/state, assigned user, etc. - only fields listed for that model) so the user sees
   real details, not just an ID. If the user asks a follow-up ("which are they?", "show
   details") reuse the model from the previous turn.
6. Never fabricate record IDs, field values, or search results - only reference data that
   was actually returned to you earlier in this conversation.

Available models for this request:
{model_context}
"""


class AiConversation(models.Model):
    _name = "ai.conversation"
    _description = "Otomater AI - Conversation"
    _order = "write_date desc"
    _rec_name = "name"

    name = fields.Char(default=lambda self: _("New Conversation"))
    user_id = fields.Many2one(
        "res.users", default=lambda self: self.env.user, required=True, index=True
    )
    provider_id = fields.Many2one("ai.provider", string="Provider")
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company
    )
    message_ids = fields.One2many("ai.message", "conversation_id", string="Messages")
    message_count = fields.Integer(compute="_compute_stats", store=True)
    total_tokens = fields.Integer(compute="_compute_stats", store=True)
    total_cost = fields.Float(compute="_compute_stats", store=True, digits=(16, 6))
    is_pinned = fields.Boolean(string="Pinned", default=False)
    active = fields.Boolean(default=True)

    @api.depends("message_ids.tokens_input", "message_ids.tokens_output", "message_ids.cost")
    def _compute_stats(self):
        for conv in self:
            conv.message_count = len(conv.message_ids)
            conv.total_tokens = sum(
                m.tokens_input + m.tokens_output for m in conv.message_ids
            )
            conv.total_cost = sum(m.cost for m in conv.message_ids)

    def _get_provider(self):
        self.ensure_one()
        provider = self.provider_id
        if not provider:
            provider = self.env["ai.provider"].get_default_provider(
                self.company_id.id
            )
        return provider

    def _build_message_history(self, extra_system_prompt=None):
        self.ensure_one()
        history = []
        if extra_system_prompt:
            history.append({"role": "system", "content": extra_system_prompt})
        history += [
            {"role": m.role, "content": m.content}
            for m in self.message_ids
            if m.role in ("user", "assistant")
        ]
        return history

    def _recent_tool_models(self, limit=2):
        """Models used by the latest successful tool calls in this conversation."""
        logs = self.env["ai.audit.log"].sudo().search(
            [
                ("conversation_id", "=", self.id),
                ("target_model", "!=", False),
                ("status", "=", "success"),
            ],
            order="id desc",
            limit=10,
        )
        models_ = []
        for log in logs:
            if log.target_model not in models_:
                models_.append(log.target_model)
        return models_[:limit]

    def _build_planner_prompt(self, content, agent=None):
        scoring_query = content
        # Follow-up messages ("which are they?") carry no topic words, so
        # also score against the previous user messages in this conversation.
        prev = self.message_ids.filtered(lambda m: m.role == "user")[-3:-1] if self.message_ids else []
        if prev:
            scoring_query = "%s %s" % (content, " ".join(m.content or "" for m in prev))
        pinned_models = self._recent_tool_models()
        if agent and agent.keywords:
            scoring_query = "%s %s" % (content, agent.keywords.replace(",", " "))
        context = self.env["ai.introspection"].build_tool_context(
            scoring_query, pinned_models=pinned_models
        )
        if context:
            lines = []
            for entry in context:
                access = entry["access"]
                ops = [op for op, allowed in access.items() if allowed]
                field_names = ", ".join(list(entry["fields"].keys())[:20])
                lines.append(
                    "- %s (%s) | access: %s | fields: %s"
                    % (entry["model"], entry["description"], ", ".join(ops), field_names)
                )
            model_context = "\n".join(lines)
        else:
            model_context = "(none matched this request)"
        persona_block = agent.build_persona_prompt() if agent and not agent.is_supervisor else ""
        prompt = PLANNER_SYSTEM_PROMPT.format(persona_block=persona_block, model_context=model_context)
        today = fields.Date.context_today(self)
        return prompt + (
            "\nToday's date is %s. For 'today' use a domain on create_date such as "
            "[[\"create_date\", \">=\", \"%s 00:00:00\"]] (user's timezone may shift this slightly). "
            "Words like 'lead', 'leads', 'student' refer to the matching model in the list above.\n"
            % (today, today)
        )

    @staticmethod
    def _parse_plan(raw_content):
        """Best-effort JSON parse of the model's plan. Falls back to a plain
        chat action if the provider didn't return valid JSON (small/local
        models in particular don't always follow instructions perfectly) -
        we degrade gracefully rather than surfacing a parse error."""
        text = (raw_content or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        text = text.strip()
        try:
            plan = json.loads(text)
            if isinstance(plan, dict) and "action" in plan:
                return plan
        except (ValueError, TypeError):
            pass
        return {"action": "chat", "model": None, "params": {}, "message": raw_content or ""}

    def _describe_destructive_action(self, plan):
        tool = plan.get("action")
        model_name = plan.get("model")
        params = plan.get("params") or {}
        if tool == "create_record":
            return _("Create a new %s record with: %s") % (model_name, params.get("values"))
        if tool == "update_record":
            return _("Update %s record(s) %s with: %s") % (
                model_name, params.get("res_ids"), params.get("values"),
            )
        if tool == "delete_record":
            return _("Delete %s record(s): %s") % (model_name, params.get("res_ids"))
        if tool == "call_method":
            return _("Call method '%s' on %s record(s) %s") % (
                params.get("method_name"), model_name, params.get("res_ids"),
            )
        if tool == "execute_server_action":
            return _("Run server action #%s") % params.get("action_id")
        return plan.get("message") or _("Perform an AI-proposed action.")

    def _format_read_result(self, tool, outcome):
        if not outcome["ok"]:
            return _("I couldn't retrieve that: %s") % outcome["error"]
        data = outcome["data"]
        if tool == "count_records":
            return _("Count: %s") % data.get("count")
        if tool == "read_record":
            return json.dumps(data, default=str, indent=2)[:4000]
        if tool == "search_records":
            records = data.get("records", [])
            if not records:
                return _("No matching records found.")
            lines = []
            for rec in records[:20]:
                label = rec.get("display_name") or rec.get("name") or ""
                extras = []
                for k, v in rec.items():
                    if k in ("id", "display_name", "name") or v in (False, None, "", []):
                        continue
                    if isinstance(v, (list, tuple)) and len(v) == 2 and isinstance(v[0], int):
                        v = v[1]
                    extras.append("%s: %s" % (k, v))
                lines.append(
                    "- #%s %s%s" % (rec.get("id"), label, (" | " + " | ".join(extras)) if extras else "")
                )
            more = ""
            if data.get("count", 0) > len(records):
                more = _("\n(showing %s of %s)") % (len(records), data["count"])
            return "\n".join(lines) + more
        if tool == "search_knowledge":
            results = data.get("results", [])
            if not results:
                return _("Nothing relevant found in the Knowledge Base.")
            lines = []
            for item in results:
                lines.append(
                    "- [%s] (%.0f%% match) %s"
                    % (item["document"], item["score"] * 100, item["content"][:300])
                )
            return "\n".join(lines)
        return json.dumps(data, default=str)[:4000]

    def action_send_message(self, content):
        """Append a user message, ask the AI to plan a response (chat reply
        or a tool call), execute read-only tools immediately, gate
        destructive tools behind ai.pending.action, and log every round
        trip to the audit log.

        Returns the last ai.message record created for this turn.
        """
        self.ensure_one()
        provider = self._get_provider()
        if not provider:
            raise ValueError(_(
                "No AI provider is configured. Ask an administrator to set "
                "one up under Otomater AI > AI Settings > Providers."
            ))

        if self.name == _("New Conversation") or not self.name:
            self.name = content[:60]

        self.env["ai.message"].create(
            {"conversation_id": self.id, "role": "user", "content": content}
        )

        agent, matched_keywords = self.env["ai.agent"].find_best_agent(content)
        _logger.debug(
            "Otomater AI delegation: agent=%s matched=%s",
            agent.code if agent else None, matched_keywords,
        )

        system_prompt = self._build_planner_prompt(content, agent=agent)
        history = self._build_message_history(extra_system_prompt=system_prompt)
        result = provider.call(history)

        if result["status"] != "success":
            assistant_message = self.env["ai.message"].create(
                {
                    "conversation_id": self.id,
                    "role": "assistant",
                    "content": "",
                    "agent_id": agent.id if agent else False,
                    "status": "error",
                    "error_message": result["error_message"],
                }
            )
            self._log_audit(provider, content, "chat", None, None, result, None)
            return assistant_message

        plan = self._parse_plan(result["content"])
        action = plan.get("action") or "chat"
        reply_text = plan.get("message") or ""

        if action == "chat" or action not in (DESTRUCTIVE_TOOLS | READ_ONLY_TOOLS):
            assistant_message = self.env["ai.message"].create(
                {
                    "conversation_id": self.id,
                    "role": "assistant",
                    "content": reply_text,
                    "agent_id": agent.id if agent else False,
                    "tokens_input": result["tokens_input"],
                    "tokens_output": result["tokens_output"],
                    "cost": result["cost"],
                    "execution_time": result["execution_time"],
                    "status": "success",
                }
            )
            self._log_audit(provider, content, "chat", None, None, result, reply_text)
            return assistant_message

        model_name = plan.get("model")
        params = plan.get("params") or {}
        if params.get("model_name") is None and model_name:
            params["model_name"] = model_name

        if action in READ_ONLY_TOOLS:
            outcome = self.env["ai.tool.executor"].execute_tool(action, params)
            formatted = self._format_read_result(action, outcome)
            full_content = (reply_text + "\n\n" + formatted).strip() if reply_text else formatted
            assistant_message = self.env["ai.message"].create(
                {
                    "conversation_id": self.id,
                    "role": "assistant",
                    "content": full_content,
                    "agent_id": agent.id if agent else False,
                    "tokens_input": result["tokens_input"],
                    "tokens_output": result["tokens_output"],
                    "cost": result["cost"],
                    "execution_time": result["execution_time"],
                    "status": "success" if outcome["ok"] else "error",
                    "error_message": outcome.get("error") if not outcome["ok"] else False,
                }
            )
            self._log_audit(
                provider, content, "read_tool", action, model_name, result, full_content,
                params=params, tool_status="success" if outcome["ok"] else "error",
                tool_error=outcome.get("error"),
            )
            return assistant_message

        # Destructive tool: create the confirmation gate, do NOT execute.
        description = self._describe_destructive_action(plan)
        assistant_message = self.env["ai.message"].create(
            {
                "conversation_id": self.id,
                "role": "assistant",
                "message_type": "confirmation",
                "agent_id": agent.id if agent else False,
                "content": (reply_text + "\n\n" + description).strip() if reply_text else description,
                "tokens_input": result["tokens_input"],
                "tokens_output": result["tokens_output"],
                "cost": result["cost"],
                "execution_time": result["execution_time"],
                "status": "success",
            }
        )
        pending = self.env["ai.pending.action"].create(
            {
                "conversation_id": self.id,
                "message_id": assistant_message.id,
                "user_id": self.env.user.id,
                "tool_name": action,
                "target_model": model_name,
                "params": json.dumps(params, default=str),
                "description": description,
            }
        )
        assistant_message.pending_action_id = pending.id
        self._log_audit(
            provider, content, "write_tool", action, model_name, result, description,
            params=params, tool_status="success",
        )
        return assistant_message

    def _log_audit(self, provider, prompt, category, tool_name, model_name, result,
                    response_text, params=None, tool_status=None, tool_error=None):
        self.env["ai.audit.log"].sudo().create(
            {
                "user_id": self.env.user.id,
                "conversation_id": self.id,
                "provider_id": provider.id if provider else False,
                "action_category": category,
                "tool_name": tool_name,
                "target_model": model_name,
                "params": json.dumps(params, default=str) if params else False,
                "prompt": prompt,
                "response": response_text or result.get("error_message") or "",
                "tokens_input": result.get("tokens_input", 0),
                "tokens_output": result.get("tokens_output", 0),
                "cost": result.get("cost", 0.0),
                "execution_time": result.get("execution_time", 0.0),
                "status": tool_status or result.get("status"),
                "error_message": tool_error or result.get("error_message"),
            }
        )

    @api.model
    def get_or_create_open_conversation(self, conversation_id=False):
        if conversation_id:
            conv = self.browse(conversation_id).exists()
            if conv and conv.user_id == self.env.user:
                return conv
        return self.create({"user_id": self.env.user.id})

    def action_send_message_rpc(self, content):
        """JS-facing wrapper. Must stay instance-callable via RPC and
        return plain JSON-serializable data only."""
        message = self.action_send_message(content)
        return {
            "conversation_id": self.id,
            "conversation_name": self.name,
            "message": {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "message_type": message.message_type,
                "pending_action_id": message.pending_action_id.id or False,
                "agent_name": message.agent_id.name or False,
                "status": message.status,
                "error_message": message.error_message,
                "tokens_input": message.tokens_input,
                "tokens_output": message.tokens_output,
                "cost": message.cost,
            },
        }
