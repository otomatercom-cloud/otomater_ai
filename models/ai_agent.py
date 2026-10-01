# -*- coding: utf-8 -*-
"""
Specialized agents for Otomater AI (Phase 3).

Delegation is intentionally a fast, deterministic, zero-LLM-call keyword
match rather than an extra "ask the LLM which agent should handle this"
round trip. Two reasons:
  1. Cost/latency - an extra planning call per message would roughly double
     token spend and response time for every single chat turn.
  2. Determinism - the same message always routes to the same agent,
     which matters for audit/debugging ("why did the AI answer as the
     Purchase Agent here?").

The Supervisor Agent (is_supervisor=True) is the fallback used whenever no
specialized agent's keywords clearly match - it has no domain bias of its
own and behaves like Phase 2's general assistant.
"""

import re

from odoo import fields, models

_TOKEN_RE = re.compile(r"[a-zA-Z]+")


class AiAgent(models.Model):
    _name = "ai.agent"
    _description = "Otomater AI - Specialized Agent"
    _order = "sequence, id"

    name = fields.Char(required=True)
    code = fields.Char(required=True, help="Stable technical code, e.g. hr_agent.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    is_supervisor = fields.Boolean(
        string="Fallback / Supervisor",
        help="Used whenever no specialized agent's keywords match. Exactly "
        "one active agent should have this checked.",
    )
    description = fields.Text(
        string="Persona",
        help="Injected into the system prompt to give this agent its voice "
        "and domain focus, e.g. 'You are the HR Agent, specialized in "
        "employees, leave, attendance and payroll.'",
    )
    keywords = fields.Char(
        help="Comma-separated words used both to route a message to this "
        "agent and to bias which models get shortlisted for it, "
        "e.g. 'employee, leave, attendance, payroll, hr'."
    )

    _sql_constraints = [
        ("code_uniq", "unique(code)", "Agent code must be unique."),
    ]

    def _keyword_set(self):
        self.ensure_one()
        return set(
            t.strip().lower() for t in (self.keywords or "").split(",") if t.strip()
        )

    def find_best_agent(self, query):
        """Return the (agent, matched_keywords) best matching `query`, or
        the supervisor/fallback agent if nothing scores above zero."""
        def _st(t):
            t = t.lower()
            for suf in ("ies", "es", "s"):
                if len(t) > 3 and t.endswith(suf):
                    return t[: -len(suf)] + ("y" if suf == "ies" else "")
            return t

        query_tokens = set(_st(t) for t in _TOKEN_RE.findall(query or ""))
        best_agent = None
        best_score = 0
        best_matches = set()
        for agent in self.search([("active", "=", True), ("is_supervisor", "=", False)]):
            overlap = query_tokens & set(_st(k) for k in agent._keyword_set())
            if len(overlap) > best_score:
                best_score = len(overlap)
                best_agent = agent
                best_matches = overlap

        if best_agent:
            return best_agent, best_matches

        supervisor = self.search([("active", "=", True), ("is_supervisor", "=", True)], limit=1)
        return supervisor, set()

    def build_persona_prompt(self):
        self.ensure_one()
        if not self.description:
            return ""
        return "Your specialized role right now: %s (%s)\n%s" % (
            self.name, self.code, self.description,
        )
