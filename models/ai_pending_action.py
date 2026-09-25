# -*- coding: utf-8 -*-
import json

from odoo import fields, models, _


class AiPendingAction(models.Model):
    _name = "ai.pending.action"
    _description = "Otomater AI - Pending Action (awaiting user confirmation)"
    _order = "create_date desc"

    conversation_id = fields.Many2one("ai.conversation", ondelete="cascade")
    message_id = fields.Many2one("ai.message", ondelete="cascade")
    user_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, index=True
    )
    tool_name = fields.Selection(
        [
            ("create_record", "Create Record"),
            ("update_record", "Update Record"),
            ("delete_record", "Delete Record"),
            ("call_method", "Call Method"),
            ("execute_server_action", "Execute Server Action"),
        ],
        required=True,
    )
    target_model = fields.Char(string="Model")
    params = fields.Text(help="JSON-encoded parameters for the tool call.")
    description = fields.Text(string="What this will do")
    state = fields.Selection(
        [
            ("pending", "Pending Confirmation"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("executed", "Executed"),
            ("error", "Error"),
        ],
        default="pending",
        required=True,
    )
    result = fields.Text(readonly=True)
    error_message = fields.Text(readonly=True)

    def _get_params(self):
        self.ensure_one()
        try:
            return json.loads(self.params or "{}")
        except ValueError:
            return {}

    def _make_reply(self, role, content, status="success", error_message=False):
        """Create an ai.message when this pending action belongs to a chat
        conversation; otherwise (API-created pending actions have none)
        just build an equivalent plain dict so callers have one consistent
        return shape either way."""
        self.ensure_one()
        if self.conversation_id:
            message = self.env["ai.message"].create(
                {
                    "conversation_id": self.conversation_id.id,
                    "role": role,
                    "content": content,
                    "status": status,
                    "error_message": error_message,
                }
            )
            return {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "message_type": message.message_type,
                "status": message.status,
            }
        return {
            "id": False,
            "role": role,
            "content": content,
            "message_type": "text",
            "status": status,
        }

    def _approve(self):
        """Execute the previously-proposed tool call as the SAME user who
        approves it (self.env.user) - ACL/record rules apply exactly as if
        they'd done this by hand in the UI. Returns a plain dict describing
        the reply (and creates an ai.message too, if there's a conversation
        to attach it to)."""
        self.ensure_one()
        if self.state != "pending":
            return self._make_reply("assistant", _("This action is no longer pending."))

        executor = self.env["ai.tool.executor"]
        outcome = executor.execute_tool(self.tool_name, self._get_params())

        if outcome["ok"]:
            self.write(
                {
                    "state": "executed",
                    "result": json.dumps(outcome["data"], default=str),
                }
            )
            reply = _("Done - %s") % outcome["data"]
            status = "success"
        else:
            self.write({"state": "error", "error_message": outcome["error"]})
            reply = _("I couldn't complete that: %s") % outcome["error"]
            status = "error"

        result = self._make_reply(
            "assistant", reply, status=status,
            error_message=outcome.get("error") if status == "error" else False,
        )
        self.env["ai.audit.log"].sudo().create(
            {
                "user_id": self.env.user.id,
                "conversation_id": self.conversation_id.id,
                "action_category": "write_tool",
                "tool_name": self.tool_name,
                "target_model": self.target_model,
                "params": self.params,
                "prompt": self.description,
                "response": reply,
                "status": "success" if outcome["ok"] else "error",
                "error_message": outcome.get("error") if not outcome["ok"] else False,
            }
        )
        return result

    def _reject(self):
        self.ensure_one()
        if self.state != "pending":
            return self._make_reply("assistant", _("This action is no longer pending."))
        self.write({"state": "rejected"})
        result = self._make_reply("assistant", _("Okay, I won't do that."))
        self.env["ai.audit.log"].sudo().create(
            {
                "user_id": self.env.user.id,
                "conversation_id": self.conversation_id.id,
                "action_category": "write_tool",
                "tool_name": self.tool_name,
                "target_model": self.target_model,
                "params": self.params,
                "prompt": self.description,
                "response": "Rejected by user",
                "status": "cancelled",
            }
        )
        return result

    def action_approve(self):
        """Backend button entry point (form/list view) - returns a
        notification popup."""
        result = self._approve()
        return self._notify(result["content"], "success" if result["status"] != "error" else "danger")

    def action_reject(self):
        """Backend button entry point (form/list view) - returns a
        notification popup."""
        result = self._reject()
        return self._notify(result["content"], "success")

    def action_approve_rpc(self):
        """Chat-widget / REST API entry point - returns a plain JSON dict
        so it can be appended straight into the conversation view."""
        return self._approve()

    def action_reject_rpc(self):
        """Chat-widget / REST API entry point - returns a plain JSON dict
        so it can be appended straight into the conversation view."""
        return self._reject()

    def _notify(self, message, ntype):
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {"message": message, "type": ntype, "sticky": False},
        }
