# -*- coding: utf-8 -*-
"""
Otomater AI REST API (Phase 4).

Authentication: API Key only, for real, tested end-to-end (Otomater AI >
API Keys, per-user, revocable). Every call runs strictly as
`api_key.user_id` - normal Odoo ACL/record rules apply exactly the same
as the chat widget; a key can never do more than that user could do by
logging in themselves.

OAuth2 / JWT: NOT implemented as a full authorization server here - that
is a substantial separate project (token issuance, refresh, scope
management, revocation lists) that would be irresponsible to fake with a
minimal implementation. Instead, `_authenticate()` below is a single,
clearly-marked extension point: if you have an existing OAuth2/JWT
provider (Keycloak, Auth0, an API gateway, etc.), validate the incoming
token there and resolve it to a res.users record in this one function -
every route in this file already works unchanged after that.

All routes accept/return JSON. Every response has at least {"ok": bool},
plus "error" on failure. HTTP status codes are set accordingly.
"""

import json

from odoo import fields, http
from odoo.http import request

from ..models.ai_tool_executor import ALL_TOOLS, READ_ONLY_TOOLS


def _json_body():
    try:
        return json.loads(request.httprequest.data or b"{}")
    except ValueError:
        return {}


def _error(message, status=400):
    return request.make_json_response({"ok": False, "error": message}, status=status)


def _ok(data, status=200):
    payload = {"ok": True}
    payload.update(data)
    return request.make_json_response(payload, status=status)


class OtomaterAiApiController(http.Controller):

    def _authenticate(self, data):
        """Returns (env, None) on success or (None, error_response) on
        failure. See module docstring for how to plug in OAuth2/JWT here
        instead of/in addition to API keys."""
        key = data.get("api_key") or request.httprequest.headers.get("X-Api-Key")
        if not key:
            return None, _error("Missing api_key", status=401)

        api_key = request.env["ai.api.key"].sudo().search(
            [("key", "=", key), ("active", "=", True)], limit=1
        )
        if not api_key or not api_key.user_id.active:
            return None, _error("Invalid or inactive API key", status=401)

        api_key.sudo().write({"last_used": fields.Datetime.now()})
        return request.env(user=api_key.user_id.id), None

    # -----------------------------------------------------------------
    # Chat
    # -----------------------------------------------------------------
    @http.route("/otomater_ai/api/chat", type="http", auth="public",
                methods=["POST"], csrf=False)
    def api_chat(self, **kwargs):
        data = _json_body()
        env, err = self._authenticate(data)
        if err:
            return err

        message_text = data.get("message")
        if not message_text:
            return _error("'message' is required")

        conversation_id = data.get("conversation_id")
        Conversation = env["ai.conversation"]
        conversation = Conversation.get_or_create_open_conversation(conversation_id or False)

        try:
            message = conversation.action_send_message(message_text)
        except ValueError as exc:
            return _error(str(exc))

        return _ok({
            "conversation_id": conversation.id,
            "message": {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "message_type": message.message_type,
                "pending_action_id": message.pending_action_id.id or False,
                "agent": message.agent_id.name or False,
                "status": message.status,
                "error_message": message.error_message,
            },
        })

    # -----------------------------------------------------------------
    # Search (shortcut for the search_records tool)
    # -----------------------------------------------------------------
    @http.route("/otomater_ai/api/search", type="http", auth="public",
                methods=["POST"], csrf=False)
    def api_search(self, **kwargs):
        data = _json_body()
        env, err = self._authenticate(data)
        if err:
            return err

        if not data.get("model"):
            return _error("'model' is required")

        params = {
            "model_name": data["model"],
            "domain": data.get("domain") or [],
            "fields": data.get("fields"),
            "limit": data.get("limit", 20),
        }
        outcome = env["ai.tool.executor"].execute_tool("search_records", params)
        if not outcome["ok"]:
            return _error(outcome["error"], status=422)
        return _ok({"data": outcome["data"]})

    # -----------------------------------------------------------------
    # Knowledge search
    # -----------------------------------------------------------------
    @http.route("/otomater_ai/api/knowledge_search", type="http", auth="public",
                methods=["POST"], csrf=False)
    def api_knowledge_search(self, **kwargs):
        data = _json_body()
        env, err = self._authenticate(data)
        if err:
            return err

        if not data.get("query"):
            return _error("'query' is required")

        outcome = env["ai.tool.executor"].execute_tool(
            "search_knowledge", {"query": data["query"], "limit": data.get("limit", 5)}
        )
        if not outcome["ok"]:
            return _error(outcome["error"], status=422)
        return _ok({"data": outcome["data"]})

    # -----------------------------------------------------------------
    # Generic tool execution (read tools run immediately; destructive
    # tools create a pending action awaiting confirmation, same as chat)
    # -----------------------------------------------------------------
    @http.route("/otomater_ai/api/execute", type="http", auth="public",
                methods=["POST"], csrf=False)
    def api_execute(self, **kwargs):
        data = _json_body()
        env, err = self._authenticate(data)
        if err:
            return err

        tool_name = data.get("tool_name")
        params = data.get("params") or {}
        if tool_name not in ALL_TOOLS:
            return _error("Unknown tool_name '%s'. Valid tools: %s" % (
                tool_name, ", ".join(sorted(ALL_TOOLS))
            ))

        if tool_name in READ_ONLY_TOOLS:
            outcome = env["ai.tool.executor"].execute_tool(tool_name, params)
            if not outcome["ok"]:
                return _error(outcome["error"], status=422)
            return _ok({"data": outcome["data"]})

        # Destructive: create a pending action, do NOT execute yet.
        pending = env["ai.pending.action"].create({
            "user_id": env.user.id,
            "tool_name": tool_name,
            "target_model": params.get("model_name"),
            "params": json.dumps(params, default=str),
            "description": "API request: %s(%s)" % (tool_name, params),
        })
        return _ok({
            "pending_action_id": pending.id,
            "state": "pending",
            "description": pending.description,
            "message": "This action requires confirmation - POST to "
                       "/otomater_ai/api/confirm with this pending_action_id.",
        })

    # -----------------------------------------------------------------
    # Confirm (approve/reject) a pending destructive action
    # -----------------------------------------------------------------
    @http.route("/otomater_ai/api/confirm", type="http", auth="public",
                methods=["POST"], csrf=False)
    def api_confirm(self, **kwargs):
        data = _json_body()
        env, err = self._authenticate(data)
        if err:
            return err

        pending_id = data.get("pending_action_id")
        if not pending_id:
            return _error("'pending_action_id' is required")

        pending = env["ai.pending.action"].browse(int(pending_id))
        if not pending.exists():
            return _error("Pending action %s not found" % pending_id, status=404)
        if pending.user_id.id != env.user.id:
            return _error("This pending action does not belong to this API key's user", status=403)

        approve = bool(data.get("approve"))
        result = pending.action_approve_rpc() if approve else pending.action_reject_rpc()
        return _ok({"state": pending.state, "result": result})

    # -----------------------------------------------------------------
    # Reports available to this user
    # -----------------------------------------------------------------
    @http.route("/otomater_ai/api/reports", type="http", auth="public",
                methods=["GET"], csrf=False)
    def api_reports(self, **kwargs):
        env, err = self._authenticate(kwargs)
        if err:
            return err

        domain = []
        if kwargs.get("model"):
            domain.append(("model", "=", kwargs["model"]))

        reports = env["ir.actions.report"].sudo().search(domain, limit=100)
        user_group_ids = set(env.user.groups_id.ids)
        visible = [
            {
                "id": r.id,
                "name": r.name,
                "report_name": r.report_name,
                "model": r.model,
                "xml_id": (r.get_external_id() or {}).get(r.id),
            }
            for r in reports
            if not r.groups_id or (set(r.groups_id.ids) & user_group_ids)
        ]
        return _ok({"reports": visible})
