# -*- coding: utf-8 -*-
"""
Scheduled Agents (Phase 3): run a fixed prompt on a recurring schedule as a
specific user, and (optionally) notify a set of recipients with the result.

Each ai.scheduled.agent record owns exactly one ir.cron record (created/
updated/deleted dynamically in Python - there is no XML data for these
crons since they are entirely user-defined). This keeps the Odoo 19
ir.cron rules (rule 16: no numbercall/doall/priority) correct automatically
regardless of what the user configures in the UI.

Safety note: any destructive tool call the scheduled prompt triggers still
goes through the normal ai.pending.action confirmation gate (see
ai_conversation.py / ai_tool_executor.py). A scheduled agent can never
create/update/delete/call a method/run a server action unattended - it can
only propose it, exactly like a live chat message would. A human still has
to open Otomater AI > Pending Actions and approve it.
"""

from odoo import api, fields, models, _


class AiScheduledAgent(models.Model):
    _name = "ai.scheduled.agent"
    _description = "Otomater AI - Scheduled Agent"
    _order = "id desc"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    agent_id = fields.Many2one("ai.agent", string="Persona")
    prompt = fields.Text(
        required=True,
        help="Exactly what will be sent to the AI each time this runs, "
        "e.g. 'Summarize today's attendance exceptions.'",
    )
    run_as_user_id = fields.Many2one(
        "res.users", required=True, default=lambda self: self.env.user,
        string="Run As",
        help="The scheduled prompt executes with THIS user's permissions - "
        "it can only see/do what they could see/do themselves.",
    )
    recipient_user_ids = fields.Many2many(
        "res.users", string="Notify",
        help="Users who get a direct message with the result each time this runs.",
    )
    interval_number = fields.Integer(default=1, required=True)
    interval_type = fields.Selection(
        [
            ("minutes", "Minutes"),
            ("hours", "Hours"),
            ("days", "Days"),
            ("weeks", "Weeks"),
            ("months", "Months"),
        ],
        default="days",
        required=True,
    )
    cron_id = fields.Many2one("ir.cron", readonly=True, ondelete="set null", copy=False)
    last_run = fields.Datetime(readonly=True)
    last_result = fields.Text(readonly=True)
    last_status = fields.Selection(
        [("success", "Success"), ("error", "Error")], readonly=True
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            record._sync_cron()
        return records

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in ("name", "active", "interval_number", "interval_type")):
            for record in self:
                record._sync_cron()
        return res

    def unlink(self):
        crons = self.mapped("cron_id")
        res = super().unlink()
        crons.unlink()
        return res

    def _sync_cron(self):
        self.ensure_one()
        model = self.env["ir.model"]._get("ai.scheduled.agent")
        values = {
            "name": "Otomater AI: %s" % self.name,
            "model_id": model.id,
            "state": "code",
            "code": "model.browse(%d)._run()" % self.id,
            "interval_number": self.interval_number,
            "interval_type": self.interval_type,
            "active": self.active,
            "user_id": self.env.ref("base.user_root").id,
        }
        if self.cron_id:
            self.cron_id.sudo().write(values)
        else:
            cron = self.env["ir.cron"].sudo().create(values)
            self.cron_id = cron.id

    def action_run_now(self):
        self.ensure_one()
        self._run()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "message": _("Run complete - see 'Last Result' below."),
                "type": "success" if self.last_status == "success" else "danger",
                "sticky": False,
            },
        }

    def _run(self):
        for agent in self:
            if not agent.run_as_user_id:
                agent.write({"last_status": "error", "last_result": "No 'Run As' user configured."})
                continue
            try:
                scoped_env = agent.env(user=agent.run_as_user_id.id)
                conversation = scoped_env["ai.conversation"].create(
                    {"user_id": agent.run_as_user_id.id, "name": agent.name}
                )
                message = conversation.action_send_message(agent.prompt)
                agent.write(
                    {
                        "last_run": fields.Datetime.now(),
                        "last_result": message.content or message.error_message or "",
                        "last_status": "error" if message.status == "error" else "success",
                    }
                )
                if agent.recipient_user_ids:
                    partner_ids = agent.recipient_user_ids.mapped("partner_id").ids
                    agent.env["mail.thread"].sudo().message_notify(
                        partner_ids=partner_ids,
                        subject=agent.name,
                        body=message.content or message.error_message or "",
                    )
            except Exception as exc:  # noqa: BLE001 - never let one bad scheduled agent break the cron
                agent.write(
                    {
                        "last_run": fields.Datetime.now(),
                        "last_status": "error",
                        "last_result": "Unexpected error: %s" % exc,
                    }
                )
