# -*- coding: utf-8 -*-
import logging
import secrets

import requests

from odoo import fields, models, _
from odoo.exceptions import UserError

from .ai_channel_service import handle_channel_message

_logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"


class AiTelegramConfig(models.Model):
    _name = "ai.telegram.config"
    _description = "Otomater AI - Telegram Bot Configuration"

    name = fields.Char(required=True)
    bot_token = fields.Char(required=True)
    webhook_secret = fields.Char(
        readonly=True, copy=False, default=lambda self: secrets.token_hex(16)
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    last_update_id = fields.Integer(default=0, readonly=True)
    last_error = fields.Text(readonly=True)

    def _api_url(self, method):
        self.ensure_one()
        return "%s/bot%s/%s" % (TELEGRAM_API, self.bot_token, method)

    def send_message(self, chat_id, text):
        self.ensure_one()
        try:
            response = requests.post(
                self._api_url("sendMessage"),
                json={"chat_id": chat_id, "text": text[:4000]},
                timeout=15,
            )
            if response.status_code >= 400:
                self.last_error = "sendMessage HTTP %s: %s" % (response.status_code, response.text[:300])
        except requests.exceptions.RequestException as exc:
            self.last_error = "sendMessage failed: %s" % exc

    def action_set_webhook(self):
        self.ensure_one()
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        if not base_url:
            raise UserError(_("Set 'web.base.url' in System Parameters first."))
        webhook_url = "%s/otomater_ai/telegram/webhook/%s" % (base_url, self.webhook_secret)
        try:
            response = requests.post(
                self._api_url("setWebhook"), json={"url": webhook_url}, timeout=15
            )
            data = response.json()
        except requests.exceptions.RequestException as exc:
            raise UserError(_("Could not reach Telegram: %s") % exc) from exc
        if not data.get("ok"):
            raise UserError(_("Telegram rejected the webhook: %s") % data.get("description"))
        self.last_error = False
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "message": _("Webhook set to %s") % webhook_url,
                "type": "success",
                "sticky": False,
            },
        }

    def action_poll_updates(self):
        """Alternative to a public webhook - safe to run from a recurring
        cron (see data/ir_cron_telegram_poll.xml, disabled by default).
        Useful for local/dev setups without a public HTTPS endpoint."""
        for config in self:
            if not config.active:
                continue
            try:
                response = requests.get(
                    config._api_url("getUpdates"),
                    params={"offset": config.last_update_id + 1, "timeout": 0},
                    timeout=20,
                )
                data = response.json()
            except requests.exceptions.RequestException as exc:
                config.last_error = "getUpdates failed: %s" % exc
                continue
            if not data.get("ok"):
                config.last_error = "getUpdates rejected: %s" % data.get("description")
                continue
            for update in data.get("result", []):
                config.last_update_id = max(config.last_update_id, update.get("update_id", 0))
                try:
                    config.process_update(update)
                except Exception as exc:  # noqa: BLE001
                    _logger.exception("Otomater AI Telegram: failed to process update")
                    config.last_error = "process_update failed: %s" % exc

    def process_update(self, update):
        self.ensure_one()
        message = update.get("message") or update.get("edited_message")
        if not message:
            return
        chat_id = str(message.get("chat", {}).get("id"))
        text = message.get("text") or message.get("caption") or ""
        if not chat_id or not text:
            return

        TelegramUser = self.env["ai.telegram.user"].sudo()

        if text.startswith("/link"):
            code = text.replace("/link", "", 1).strip()
            candidate = TelegramUser.search(
                [("link_code", "=", code), ("chat_id", "=", False)], limit=1
            ) if code else TelegramUser.browse()
            if candidate:
                candidate.write({"chat_id": chat_id, "link_code": False})
                self.send_message(
                    chat_id, _("Linked! You're now chatting as %s.") % candidate.user_id.name
                )
            else:
                self.send_message(chat_id, _("Invalid or expired link code."))
            return

        telegram_user = TelegramUser.search([("chat_id", "=", chat_id)], limit=1)
        if not telegram_user:
            self.send_message(
                chat_id,
                _("You're not linked yet. In Odoo, go to Otomater AI > My Telegram to "
                  "get a link code, then send /link <code> here."),
            )
            return

        reply = handle_channel_message(telegram_user, text)
        self.send_message(chat_id, reply)
