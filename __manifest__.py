{
    "name": "Otomater AI",
    "version": "19.0.5.0.0",
    "category": "Productivity",
    "summary": "AI Agent Platform for Odoo - conversational assistant, dynamic tools, specialized agents, knowledge base, REST API, Telegram and WhatsApp",
    "description": """
Otomater AI - Phase 5 (Telegram, WhatsApp, Dark Mode, Documentation)
========================================================================
Builds on Phase 4's knowledge base/REST API by adding:

- **Telegram** (`ai.telegram.config` / `ai.telegram.user`): link your
  Telegram account from Otomater AI > My Telegram (generates a one-time
  /link code), then chat with the AI directly from Telegram. Commands:
  /help, /report, /leave, /attendance, /crm, /stock, /chat <message>, or
  just type freely. Destructive actions still ask for a plain YES/NO
  confirmation over Telegram before executing - same confirmation gate as
  everywhere else. Works via webhook (needs a public HTTPS URL) or a
  polling cron (`action_poll_updates`, disabled by default) for local/dev
  setups without one.
- **WhatsApp Business** (`ai.whatsapp.config` / `ai.whatsapp.user`): same
  linking/command/confirmation pattern over Meta's WhatsApp Cloud API,
  including basic media receipt (images/documents get downloaded as
  attachments and acknowledged).
- **Dark mode polish**: chat and dashboard now follow Odoo's built-in
  `o_dark_mode` class instead of only shipping light-theme colors.
- **Full documentation set** under `docs/`: installation guide, developer
  guide, administrator guide, user manual, and API reference - alongside
  this README.

Phase 1-4 foundation (still included): multi-provider LLM config, dynamic
model introspection + tool execution with confirmation gate, specialized
agents, prompt library, scheduled agents, knowledge base, REST API,
chat/dashboard UI, audit log, security groups.
""",
    "author": "Otomater",
    "website": "https://otomater.com",
    "license": "LGPL-3",
    "depends": ["base", "mail", "web"],
    "data": [
        "security/security_groups.xml",
        "security/ir.model.access.csv",
        "security/ir_rule.xml",
        "data/ai_agent_data.xml",
        "views/ai_provider_views.xml",
        "views/ai_conversation_views.xml",
        "views/ai_pending_action_views.xml",
        "views/ai_agent_views.xml",
        "views/ai_prompt_views.xml",
        "views/ai_scheduled_agent_views.xml",
        "views/ai_knowledge_document_views.xml",
        "views/ai_api_key_views.xml",
        "views/ai_telegram_views.xml",
        "views/ai_whatsapp_views.xml",
        "views/ai_audit_log_views.xml",
        "views/ai_chat_templates.xml",
        "views/ai_dashboard_templates.xml",
        "data/ai_prompt_data.xml",
        "data/ir_cron_telegram_poll.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "otomater_ai/static/src/css/otomater_ai.css",
            "otomater_ai/static/src/js/chat/chat_component.js",
            "otomater_ai/static/src/js/dashboard/dashboard_component.js",
            "otomater_ai/static/src/xml/chat_templates.xml",
            "otomater_ai/static/src/xml/dashboard_templates.xml",
        ],
    },
    "installable": True,
    "application": True,
    "auto_install": False,
}
