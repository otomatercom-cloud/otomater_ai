# -*- coding: utf-8 -*-
import secrets

from odoo import fields, models, _


class AiTelegramUser(models.Model):
    _name = "ai.telegram.user"
    _description = "Otomater AI - Telegram Link"
    _order = "id desc"

    user_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user, index=True
    )
    chat_id = fields.Char(readonly=True, copy=False, index=True)
    link_code = fields.Char(readonly=True, copy=False)
    conversation_id = fields.Many2one("ai.conversation", readonly=True, copy=False)
    awaiting_pending_action_id = fields.Many2one(
        "ai.pending.action", readonly=True, copy=False
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("chat_id_uniq", "unique(chat_id)", "This Telegram chat is already linked to a user."),
    ]

    def action_generate_link_code(self):
        self.ensure_one()
        self.write({"link_code": secrets.token_hex(3), "chat_id": False})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "message": _(
                    "Send this to the bot on Telegram: /link %s"
                ) % self.link_code,
                "type": "success",
                "sticky": True,
            },
        }

    def action_unlink_telegram(self):
        self.ensure_one()
        self.write({"chat_id": False, "link_code": False})
