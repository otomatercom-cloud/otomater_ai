# -*- coding: utf-8 -*-
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class OtomaterAiTelegramController(http.Controller):

    @http.route(
        "/otomater_ai/telegram/webhook/<string:secret>",
        type="http", auth="public", methods=["POST"], csrf=False,
    )
    def telegram_webhook(self, secret, **kwargs):
        config = request.env["ai.telegram.config"].sudo().search(
            [("webhook_secret", "=", secret), ("active", "=", True)], limit=1
        )
        if not config:
            return request.make_json_response({"ok": False}, status=404)

        try:
            update = json.loads(request.httprequest.data or b"{}")
        except ValueError:
            return request.make_json_response({"ok": False}, status=400)

        try:
            config.process_update(update)
        except Exception:  # noqa: BLE001 - Telegram will retry on non-2xx; log and 200 anyway
            _logger.exception("Otomater AI Telegram webhook: failed to process update")

        # Telegram expects a fast 200 regardless, or it will keep retrying.
        return request.make_json_response({"ok": True})
