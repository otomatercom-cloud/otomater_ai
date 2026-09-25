# -*- coding: utf-8 -*-
from odoo import fields, models


class AiPrompt(models.Model):
    _name = "ai.prompt"
    _description = "Otomater AI - Prompt Library"
    _order = "sequence, id"

    name = fields.Char(required=True)
    category = fields.Selection(
        [
            ("hr", "HR"),
            ("sales", "Sales"),
            ("crm", "CRM"),
            ("finance", "Finance"),
            ("support", "Support"),
            ("inventory", "Inventory"),
            ("marketing", "Marketing"),
            ("system_admin", "System Administration"),
            ("other", "Other"),
        ],
        default="other",
        required=True,
    )
    agent_id = fields.Many2one(
        "ai.agent", string="Suggested Agent",
        help="Optional - if set, using this prompt routes straight to this agent.",
    )
    content = fields.Text(required=True, string="Prompt Text")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    use_count = fields.Integer(default=0, readonly=True)

    def action_use_prompt(self):
        """Opens the AI Chat client action with this prompt pre-filled into
        the input box, ready for the user to review/edit and send."""
        self.ensure_one()
        self.use_count += 1
        return {
            "type": "ir.actions.client",
            "tag": "otomater_ai.chat",
            "name": "AI Chat",
            "params": {"draft": self.content},
        }
