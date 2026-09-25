# -*- coding: utf-8 -*-
import time

from odoo import api, fields, models, _
from odoo.exceptions import UserError

from .provider_adapter import call_provider, call_embedding_provider, ProviderError


class AiProvider(models.Model):
    _name = "ai.provider"
    _description = "Otomater AI - LLM Provider Configuration"
    _order = "sequence, id"

    name = fields.Char(required=True)
    code = fields.Selection(
        [
            ("openai", "OpenAI"),
            ("anthropic", "Claude (Anthropic)"),
            ("gemini", "Gemini"),
            ("ollama", "Ollama"),
            ("azure_openai", "Azure OpenAI"),
            ("openrouter", "OpenRouter"),
        ],
        required=True,
    )
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    is_default = fields.Boolean(
        string="Default Provider",
        help="Used whenever a conversation does not specify a provider explicitly.",
    )
    api_key = fields.Char(string="API Key")
    api_base_url = fields.Char(
        string="API Base URL",
        help="Override the provider's default endpoint. Required for Azure OpenAI "
        "(full deployment URL) and for self-hosted Ollama instances.",
    )
    api_version = fields.Char(
        string="API Version",
        help="Only used by Azure OpenAI (e.g. 2024-06-01).",
    )
    model = fields.Char(
        string="Model",
        help="Model identifier passed to the provider, e.g. gpt-4o-mini, "
        "claude-sonnet-4-6, gemini-2.0-flash, llama3.1.",
    )
    temperature = fields.Float(default=0.7)
    max_tokens = fields.Integer(string="Max Tokens", default=1024)
    timeout = fields.Integer(string="Timeout (s)", default=60)
    retry_count = fields.Integer(string="Retry Count", default=1)
    cost_per_1k_input = fields.Float(string="Cost per 1K Input Tokens", digits=(16, 6))
    cost_per_1k_output = fields.Float(string="Cost per 1K Output Tokens", digits=(16, 6))
    is_embedding_provider = fields.Boolean(
        string="Use for Embeddings",
        help="Mark this provider as the one used to generate embeddings for the "
        "Knowledge Base. Only OpenAI, Azure OpenAI, Gemini and Ollama support "
        "embeddings here - Claude and OpenRouter do not.",
    )
    embedding_model = fields.Char(
        help="Embedding model identifier, e.g. text-embedding-3-small, "
        "text-embedding-004, nomic-embed-text. Falls back to a sensible "
        "per-provider default if left blank.",
    )
    company_id = fields.Many2one(
        "res.company", default=lambda self: self.env.company, string="Company"
    )
    last_test_result = fields.Text(string="Last Connection Test", readonly=True)

    @api.constrains("is_embedding_provider")
    def _check_embedding_capable(self):
        for provider in self:
            if provider.is_embedding_provider and provider.code not in (
                "openai", "azure_openai", "gemini", "ollama",
            ):
                raise UserError(
                    _("'%s' does not support embeddings. Choose OpenAI, Azure "
                      "OpenAI, Gemini, or Ollama as the embedding provider.")
                    % provider.code
                )

    @api.constrains("is_embedding_provider", "company_id")
    def _check_single_default_embedding(self):
        for provider in self:
            if not provider.is_embedding_provider:
                continue
            domain = [
                ("is_embedding_provider", "=", True),
                ("company_id", "=", provider.company_id.id),
                ("id", "!=", provider.id),
            ]
            if self.search_count(domain):
                raise UserError(
                    _("Only one default embedding provider is allowed per company.")
                )

    @api.constrains("is_default", "company_id")
    def _check_single_default(self):
        for provider in self:
            if not provider.is_default:
                continue
            domain = [
                ("is_default", "=", True),
                ("company_id", "=", provider.company_id.id),
                ("id", "!=", provider.id),
            ]
            if self.search_count(domain):
                raise UserError(
                    _("Only one default AI provider is allowed per company. "
                      "Un-default the existing one first.")
                )

    def _get_config(self):
        self.ensure_one()
        return {
            "api_key": self.api_key,
            "api_base_url": self.api_base_url,
            "api_version": self.api_version,
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
        }

    def _compute_cost(self, tokens_input, tokens_output):
        self.ensure_one()
        cost = (tokens_input / 1000.0) * self.cost_per_1k_input
        cost += (tokens_output / 1000.0) * self.cost_per_1k_output
        return cost

    def call(self, messages):
        """Call this provider with a normalized message list.

        Returns a dict: content, tokens_input, tokens_output, cost,
        execution_time, status ('success'/'error'), error_message.
        """
        self.ensure_one()
        config = self._get_config()
        attempts = max(1, self.retry_count)
        last_error = None
        start = time.time()
        for attempt in range(attempts):
            try:
                result = call_provider(self.code, config, messages)
                execution_time = time.time() - start
                cost = self._compute_cost(
                    result["tokens_input"], result["tokens_output"]
                )
                return {
                    "content": result["content"],
                    "tokens_input": result["tokens_input"],
                    "tokens_output": result["tokens_output"],
                    "cost": cost,
                    "execution_time": execution_time,
                    "status": "success",
                    "error_message": False,
                }
            except ProviderError as exc:
                last_error = str(exc)
        execution_time = time.time() - start
        return {
            "content": False,
            "tokens_input": 0,
            "tokens_output": 0,
            "cost": 0.0,
            "execution_time": execution_time,
            "status": "error",
            "error_message": last_error,
        }

    def get_embedding(self, texts):
        """Return a list of embedding vectors, one per input text."""
        self.ensure_one()
        config = self._get_config()
        if self.embedding_model:
            config["model"] = self.embedding_model
        try:
            return call_embedding_provider(self.code, config, texts)
        except ProviderError as exc:
            raise UserError(str(exc)) from exc

    @api.model
    def get_default_embedding_provider(self, company_id=False):
        domain = [("active", "=", True), ("is_embedding_provider", "=", True)]
        if company_id:
            domain.append(("company_id", "=", company_id))
        return self.search(domain, limit=1)

    def action_test_connection(self):
        self.ensure_one()
        result = self.call(
            [{"role": "user", "content": "Reply with the single word: pong"}]
        )
        if result["status"] == "success":
            self.last_test_result = _("Success (%.2fs): %s") % (
                result["execution_time"],
                result["content"],
            )
        else:
            self.last_test_result = _("Failed: %s") % result["error_message"]
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Connection Test"),
                "message": self.last_test_result,
                "type": "success" if result["status"] == "success" else "danger",
                "sticky": False,
            },
        }

    @api.model
    def get_default_provider(self, company_id=False):
        domain = [("active", "=", True), ("is_default", "=", True)]
        if company_id:
            domain.append(("company_id", "=", company_id))
        provider = self.search(domain, limit=1)
        if not provider:
            domain = [("active", "=", True)]
            if company_id:
                domain.append(("company_id", "=", company_id))
            provider = self.search(domain, limit=1, order="sequence, id")
        return provider
