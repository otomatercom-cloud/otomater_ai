# -*- coding: utf-8 -*-
import secrets

from odoo import fields, models, _


class AiWhatsappUser(models.Model):
    _name = "ai.whatsapp.user"
    _description = "Otomater AI - WhatsApp Link"
    _order = "id desc"

    user_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, index=True
    )
    wa_number = fields.Char(string="WhatsApp Number", readonly=True, copy=False, index=True)
    link_code = fields.Char(readonly=True, copy=False)
    conversation_id = fields.Many2one("ai.conversation", readonly=True, copy=False)
    awaiting_pending_action_id = fields.Many2one(
        "ai.pending.action", readonly=True, copy=False
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("wa_number_uniq", "unique(wa_number)", "This WhatsApp number is already linked to a user."),
    ]

    def action_generate_link_code(self):
        self.ensure_one()
        self.write({"link_code": secrets.token_hex(3), "wa_number": False})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "message": _(
                    "Send this to your WhatsApp Business number: LINK %s"
                ) % self.link_code,
                "type": "success",
                "sticky": True,
            },
        }

    def action_unlink_whatsapp(self):
        self.ensure_one()
        self.write({"wa_number": False, "link_code": False})
