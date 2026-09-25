# -*- coding: utf-8 -*-
import logging

import requests

from odoo import fields, models, _

from .ai_channel_service import handle_channel_message

_logger = logging.getLogger(__name__)

GRAPH_API = "https://graph.facebook.com/v20.0"


class AiWhatsappConfig(models.Model):
    _name = "ai.whatsapp.config"
    _description = "Otomater AI - WhatsApp Business API Configuration"

    name = fields.Char(required=True)
    phone_number_id = fields.Char(
        required=True,
        help="The 'Phone number ID' from Meta's WhatsApp Business API dashboard - "
        "used both to send messages and to match incoming webhook payloads.",
    )
    access_token = fields.Char(required=True)
    verify_token = fields.Char(
        required=True,
        help="Shared secret you also enter in Meta's webhook configuration screen.",
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    last_error = fields.Text(readonly=True)

    def send_message(self, to_number, text):
        self.ensure_one()
        try:
            response = requests.post(
                "%s/%s/messages" % (GRAPH_API, self.phone_number_id),
                headers={"Authorization": "Bearer %s" % self.access_token},
                json={
                    "messaging_product": "whatsapp",
                    "to": to_number,
                    "type": "text",
                    "text": {"body": text[:4000]},
                },
                timeout=15,
            )
            if response.status_code >= 400:
                self.last_error = "send HTTP %s: %s" % (response.status_code, response.text[:300])
        except requests.exceptions.RequestException as exc:
            self.last_error = "send failed: %s" % exc

    def _fetch_media_as_attachment(self, media_id, res_model=None, res_id=None):
        """Best-effort media download (images/documents sent by the user).
        Returns an ir.attachment record, or None if anything goes wrong -
        failures here never block replying to the message."""
        self.ensure_one()
        try:
            meta = requests.get(
                "%s/%s" % (GRAPH_API, media_id),
                headers={"Authorization": "Bearer %s" % self.access_token},
                timeout=15,
            ).json()
            url = meta.get("url")
            if not url:
                return None
            content = requests.get(
                url, headers={"Authorization": "Bearer %s" % self.access_token}, timeout=30
            ).content
            import base64

            return self.env["ir.attachment"].sudo().create({
                "name": media_id,
                "datas": base64.b64encode(content),
                "res_model": res_model,
                "res_id": res_id or 0,
                "mimetype": meta.get("mime_type"),
            })
        except Exception:  # noqa: BLE001
            _logger.exception("Otomater AI WhatsApp: media download failed")
            return None

    def process_update(self, entry):
        self.ensure_one()
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                self._process_message(msg)

    def _process_message(self, msg):
        self.ensure_one()
        wa_number = msg.get("from")
        if not wa_number:
            return

        text = ""
        if msg.get("type") == "text":
            text = msg.get("text", {}).get("body", "")
        elif msg.get("type") in ("image", "document", "audio", "video"):
            media = msg.get(msg["type"], {})
            attachment = self._fetch_media_as_attachment(media.get("id"))
            text = (media.get("caption") or "").strip()
            if attachment:
                text = (text + " (attachment received: %s)" % attachment.name).strip()
            if not text:
                text = "(attachment received, no caption)"
        else:
            text = ""

        if not text:
            return

        WhatsappUser = self.env["ai.whatsapp.user"].sudo()

        if text.upper().startswith("LINK "):
            code = text[5:].strip()
            candidate = WhatsappUser.search(
                [("link_code", "=", code), ("wa_number", "=", False)], limit=1
            )
            if candidate:
                candidate.write({"wa_number": wa_number, "link_code": False})
                self.send_message(
                    wa_number, _("Linked! You're now chatting as %s.") % candidate.user_id.name
                )
            else:
                self.send_message(wa_number, _("Invalid or expired link code."))
            return

        whatsapp_user = WhatsappUser.search([("wa_number", "=", wa_number)], limit=1)
        if not whatsapp_user:
            self.send_message(
                wa_number,
                _("You're not linked yet. In Odoo, go to Otomater AI > My WhatsApp to "
                  "get a link code, then send LINK <code> here."),
            )
            return

        reply = handle_channel_message(whatsapp_user, text)
        self.send_message(wa_number, reply)
