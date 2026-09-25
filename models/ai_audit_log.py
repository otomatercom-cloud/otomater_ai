# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AiAuditLog(models.Model):
    _name = "ai.audit.log"
    _description = "Otomater AI - Audit Log"
    _order = "create_date desc"

    user_id = fields.Many2one("res.users", required=True, index=True)
    conversation_id = fields.Many2one("ai.conversation", index=True)
    message_id = fields.Many2one("ai.message")
    provider_id = fields.Many2one("ai.provider")
    action_category = fields.Selection(
        [("chat", "Chat Reply"), ("read_tool", "Read Tool Call"), ("write_tool", "Write Tool Call")],
        default="chat",
        required=True,
    )
    tool_name = fields.Char()
    target_model = fields.Char()
    params = fields.Text(help="JSON-encoded parameters passed to the tool, if any.")
    prompt = fields.Text()
    response = fields.Text()
    tokens_input = fields.Integer(default=0)
    tokens_output = fields.Integer(default=0)
    cost = fields.Float(digits=(16, 6), default=0.0)
    execution_time = fields.Float(string="Execution Time (s)", default=0.0)
    status = fields.Selection(
        [("success", "Success"), ("error", "Error"), ("cancelled", "Cancelled")], required=True
    )
    error_message = fields.Text()

    def write(self, vals):
        raise UserError(_("Audit log entries are immutable and cannot be modified."))

    def unlink(self):
        raise UserError(_("Audit log entries are immutable and cannot be deleted."))

    @api.model
    def get_dashboard_data(self):
        """Aggregate the numbers shown on the Otomater AI dashboard.

        Kept intentionally simple (grouped read_group calls) in Phase 1.
        Later phases can replace individual pieces (e.g. most-used-modules)
        without changing this method's return shape.
        """
        today_start = fields.Datetime.to_string(
            fields.Datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        )

        total_requests = self.search_count([])
        today_requests = self.search_count([("create_date", ">=", today_start)])
        failed_requests = self.search_count([("status", "=", "error")])
        success_requests = total_requests - failed_requests
        success_rate = (
            round((success_requests / total_requests) * 100, 1) if total_requests else 0.0
        )

        active_users = len(
            self.read_group([], ["user_id"], ["user_id"])
        )

        today_conversations = self.env["ai.conversation"].search_count(
            [("create_date", ">=", today_start)]
        )

        agg = self.read_group(
            [], ["tokens_input:sum", "tokens_output:sum", "cost:sum", "execution_time:avg"], []
        )
        totals = agg[0] if agg else {}

        return {
            "total_requests": total_requests,
            "today_requests": today_requests,
            "today_conversations": today_conversations,
            "active_users": active_users,
            "avg_response_time": round(totals.get("execution_time", 0.0) or 0.0, 2),
            "total_tokens": (totals.get("tokens_input") or 0) + (totals.get("tokens_output") or 0),
            "total_cost": round(totals.get("cost", 0.0) or 0.0, 4),
            "success_rate": success_rate,
            "failed_requests": failed_requests,
        }
