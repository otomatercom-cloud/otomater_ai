import re

from odoo import api, fields, models

_TOKEN_RE = re.compile(r"[a-zA-Z]+")


def _stem(token):
    t = token.lower()
    for suffix in ("ies", "es", "s"):
        if len(t) > 3 and t.endswith(suffix):
            return t[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return t


class AiModelMapping(models.Model):
    """Tells the AI what a business model means, which words refer to it,
    and which fields to show by default. A mapped model is ALWAYS preferred
    when the user's message contains one of its alias words, so "today leads
    mobile number" reliably hits `leads.logic` and not an unrelated model."""

    _name = "ai.model.mapping"
    _description = "Otomater AI - Model Mapping"
    _order = "sequence, id"

    name = fields.Char(required=True, help="Friendly name, e.g. Leads")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    model_id = fields.Many2one(
        "ir.model", string="Odoo Model", required=True, ondelete="cascade",
        domain="[('transient', '=', False)]",
    )
    model_name = fields.Char(related="model_id.model", store=True, index=True)
    aliases = fields.Char(
        help="Comma-separated words users say for this model, e.g. lead, leads, enquiry, enquiries.",
    )
    description = fields.Text(
        help="Plain-language meaning/business rules the AI should know, e.g. "
        "'Admission leads of Logic School. mobile = student mobile number. "
        "lead_quality = call outcome.'",
    )
    display_field_ids = fields.Many2many(
        "ir.model.fields", "ai_model_mapping_display_field_rel", "mapping_id", "field_id",
        string="Default Fields to Show",
        domain="[('model_id', '=', model_id), ('store', '=', True)]",
        help="Fields shown in answers when the user doesn't ask for specific ones "
        "(e.g. name, mobile, lead_quality, user_id).",
    )
    date_field_id = fields.Many2one(
        "ir.model.fields", string="Date Field for 'today / this week'",
        domain="[('model_id', '=', model_id), ('ttype', 'in', ('date', 'datetime')), ('store', '=', True)]",
        help="Used for 'created today', 'this month' etc. Leave empty to use create_date.",
    )
    company_id = fields.Many2one("res.company")

    _model_unique = models.Constraint(
        "unique(model_id)", "This model is already mapped."
    )

    def _alias_tokens(self):
        self.ensure_one()
        words = (self.aliases or "").replace(",", " ") + " " + (self.name or "")
        return {_stem(t) for t in _TOKEN_RE.findall(words)}

    @api.model
    def get_active_mappings(self):
        """{model_name: mapping record} for mappings whose model exists."""
        result = {}
        for rec in self.sudo().search([("active", "=", True)]):
            if rec.model_name and rec.model_name in self.env:
                result[rec.model_name] = rec
        return result

    def describe_for_prompt(self):
        self.ensure_one()
        parts = []
        if self.description:
            parts.append(self.description.strip().replace("\n", " "))
        names = [f.name for f in self.display_field_ids]
        if names:
            parts.append("ALWAYS include these fields in search_records: %s." % ", ".join(names))
        parts.append(
            "For date questions (today/this week/this month) filter on '%s'."
            % (self.date_field_id.name or "create_date")
        )
        return " ".join(parts)

    @api.model
    def action_seed_defaults(self, *args, **kwargs):
        self._seed_defaults()
        return True

    @api.model
    def _seed_defaults(self):
        """Create sensible mappings for models that exist in this database."""
        seeds = [
            ("Leads", "leads.logic", "lead, leads, enquiry, enquiries, prospect, student lead",
             "Admission/sales leads. 'mobile' is the student's mobile number, 'name' is the lead name.",
             ["name", "mobile", "phone", "email", "lead_quality", "leads_source", "user_id", "create_date"]),
            ("CRM Leads", "crm.lead", "crm, opportunity, opportunities, pipeline, deal",
             "Standard Odoo CRM leads/opportunities.",
             ["name", "partner_name", "phone", "email_from", "stage_id", "user_id", "expected_revenue"]),
            ("Call Logs", "lead.call.log", "call, calls, calling, call log",
             "Calls made to leads by telecallers.", []),
            ("Counselling", "lead.counselling", "counselling, counseling, counsellor, walk-in, walkin",
             "Counselling sessions linked to leads.", []),
            ("Students", "student.details", "student, students, admission, admissions, enrolled",
             "Enrolled students (admissions records).", ["name", "phone", "email"]),
            ("Employees", "hr.employee", "employee, employees, staff, faculty",
             "Company employees.", ["name", "work_phone", "mobile_phone", "department_id", "job_id"]),
            ("Contacts", "res.partner", "contact, contacts, customer, customers, vendor, partner",
             "Contacts, customers and vendors.", ["name", "phone", "email"]),
        ]
        for name, model, aliases, desc, fnames in seeds:
            model_rec = self.env["ir.model"].sudo().search([("model", "=", model)], limit=1)
            if not model_rec or self.sudo().search([("model_id", "=", model_rec.id)], limit=1):
                continue
            fields_ = self.env["ir.model.fields"].sudo().search(
                [("model_id", "=", model_rec.id), ("name", "in", fnames), ("store", "=", True)]
            )
            self.sudo().create({
                "name": name,
                "model_id": model_rec.id,
                "aliases": aliases,
                "description": desc,
                "display_field_ids": [(6, 0, fields_.ids)],
            })
