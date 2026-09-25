# -*- coding: utf-8 -*-
import secrets

from odoo import api, fields, models, _


class AiApiKey(models.Model):
    _name = "ai.api.key"
    _description = "Otomater AI - REST API Key"
    _order = "id desc"

    name = fields.Char(required=True, help="A label to remember what this key is for.")
    key = fields.Char(readonly=True, copy=False, index=True)
    user_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, index=True,
        help="API calls made with this key run with exactly this user's permissions.",
    )
    active = fields.Boolean(default=True)
    last_used = fields.Datetime(readonly=True)

    _sql_constraints = [
        ("key_uniq", "unique(key)", "This API key already exists."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals["key"] = secrets.token_hex(32)
        return super().create(vals_list)

    def action_regenerate(self):
        self.ensure_one()
        self.key = secrets.token_hex(32)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "message": _("A new key has been generated. The old key no longer works."),
                "type": "success",
                "sticky": False,
            },
        }
