# -*- coding: utf-8 -*-
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class OtomaterAiWhatsappController(http.Controller):

    @http.route(
        "/otomater_ai/whatsapp/webhook", type="http", auth="public",
        methods=["GET"], csrf=False,
    )
    def whatsapp_verify(self, **kwargs):
        mode = kwargs.get("hub.mode")
        token = kwargs.get("hub.verify_token")
        challenge = kwargs.get("hub.challenge")

        config = request.env["ai.whatsapp.config"].sudo().search(
            [("verify_token", "=", token), ("active", "=", True)], limit=1
        )
        if mode == "subscribe" and config and challenge:
            return request.make_response(challenge, headers=[("Content-Type", "text/plain")])
        return request.make_response("Forbidden", status=403)

    @http.route(
        "/otomater_ai/whatsapp/webhook", type="http", auth="public",
        methods=["POST"], csrf=False,
    )
    def whatsapp_receive(self, **kwargs):
        try:
            payload = json.loads(request.httprequest.data or b"{}")
        except ValueError:
            return request.make_json_response({"ok": False}, status=400)

        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                phone_number_id = value.get("metadata", {}).get("phone_number_id")
                if not phone_number_id or not value.get("messages"):
                    continue
                config = request.env["ai.whatsapp.config"].sudo().search(
                    [("phone_number_id", "=", phone_number_id), ("active", "=", True)], limit=1
                )
                if not config:
                    continue
                try:
                    config.process_update({"changes": [change]})
                except Exception:  # noqa: BLE001
                    _logger.exception("Otomater AI WhatsApp webhook: failed to process update")

        # Meta requires a fast 200 regardless, or it will retry/back off.
        return request.make_json_response({"ok": True})
