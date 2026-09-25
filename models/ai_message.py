# -*- coding: utf-8 -*-
from odoo import fields, models


class AiMessage(models.Model):
    _name = "ai.message"
    _description = "Otomater AI - Chat Message"
    _order = "id asc"

    conversation_id = fields.Many2one(
        "ai.conversation", required=True, ondelete="cascade", index=True
    )
    role = fields.Selection(
        [
            ("system", "System"),
            ("user", "User"),
            ("assistant", "Assistant"),
        ],
        required=True,
    )
    message_type = fields.Selection(
        [("text", "Text"), ("confirmation", "Confirmation Required")],
        default="text",
        required=True,
    )
    pending_action_id = fields.Many2one("ai.pending.action", ondelete="set null")
    agent_id = fields.Many2one("ai.agent", string="Handled By", ondelete="set null")
    content = fields.Text(required=True)
    tokens_input = fields.Integer(default=0)
    tokens_output = fields.Integer(default=0)
    cost = fields.Float(digits=(16, 6), default=0.0)
    execution_time = fields.Float(string="Execution Time (s)", default=0.0)
    status = fields.Selection(
        [("success", "Success"), ("error", "Error")], default="success"
    )
    error_message = fields.Text()
