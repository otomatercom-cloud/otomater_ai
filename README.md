# Otomater AI (Phase 5 - Telegram, WhatsApp, Dark Mode, Documentation)

Odoo 19 Community module. Phase 5 - the final phase of the original
roadmap - of the Otomater AI Agent Platform.

## What's new in Phase 5

- **Telegram** (`ai.telegram.config` / `ai.telegram.user`) - link your
  account (**Otomater AI > My Telegram**, Generate Link Code, send
  `/link <code>` to the bot), then chat from Telegram directly. Commands:
  `/help`, `/report`, `/leave`, `/attendance`, `/crm`, `/stock`, `/chat
  <message>`, or just type freely. Works via webhook (needs a public
  HTTPS URL - click **Set Webhook** on the bot config) or a disabled-by-
  default polling cron (`ai.telegram.config.action_poll_updates`) for
  local/dev setups.
- **WhatsApp Business** (`ai.whatsapp.config` / `ai.whatsapp.user`) - same
  linking (`LINK <code>`) and command pattern over Meta's WhatsApp Cloud
  API, including basic media receipt (images/documents downloaded as
  `ir.attachment` and acknowledged in the reply).
- **Confirmation gate works over chat channels too** - a destructive
  action proposed via Telegram/WhatsApp asks for a plain `YES`/`NO` reply
  before executing, going through the exact same `ai.pending.action`
  gate as the web chat and REST API. There's no separate, less-secure
  code path for chat-channel messages - both models share
  `models/ai_channel_service.py`, which calls the same
  `ai.conversation.action_send_message()` everything else uses.
- **Dark mode polish** - chat and dashboard CSS now has overrides scoped
  under Odoo's built-in `o_dark_mode` class, so both themes stay readable
  without a separate toggle.
- **Full documentation set** under `docs/`:
  `INSTALLATION_GUIDE.md`, `DEVELOPER_GUIDE.md`,
  `ADMINISTRATOR_GUIDE.md`, `USER_MANUAL.md`, `API_REFERENCE.md`.

### Trying it out

1. **Otomater AI > AI Settings > Telegram Bot** - paste a bot token from
   [@BotFather](https://t.me/BotFather), then either **Set Webhook** or
   activate the polling cron under Settings > Technical > Scheduled
   Actions.
2. **Otomater AI > My Telegram** - Generate Link Code, send `/link <code>`
   to the bot.
3. Message the bot - try `/leave` or just "what's on my plate today?".
4. Ask it to create/update something - you'll get asked to reply
   `YES`/`NO` before anything executes.

## Full roadmap - all five original phases are now complete

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Multi-provider LLM config, chat/dashboard UI, audit log | ✅ |
| 2 | Dynamic model introspection + tool execution + confirmation gate | ✅ |
| 3 | Specialized agents, Prompt Library, Scheduled Agents | ✅ |
| 4 | Knowledge Base with embeddings, REST API | ✅ |
| 5 | Telegram, WhatsApp, dark mode, full documentation | ✅ |

Natural next steps beyond the original spec, if useful later: a formal
automated test suite (`odoo.tests.TransactionCase`), pgvector-backed
Knowledge Base search for large corpora, per-provider spend caps, and a
real OAuth2/JWT authorization server for the REST API (currently a
documented extension point rather than a built-in implementation - see
`docs/API_REFERENCE.md`).

## Upgrading from Phase 4

In-place upgrade again, not a fresh install:

```bash
odoo-bin -c odoo.conf -d your_db -u otomater_ai --stop-after-init
```

New models (`ai.telegram.config`, `ai.telegram.user`,
`ai.whatsapp.config`, `ai.whatsapp.user`) are added automatically. A new,
disabled-by-default scheduled action ("Otomater AI: Poll Telegram
Updates") is created - safe to leave off if you're using a webhook
instead.

## Installation

1. Copy the `otomater_ai` folder into `E:\odoo19\custom-addons\`.
2. Ensure the `requests` Python package is available in your Odoo
   virtualenv/interpreter (`pip install requests` if not already present
   - most Odoo installs already have it as a core dependency).
3. Restart the Odoo service, update the apps list, and install
   **Otomater AI**.
4. Go to **Settings > Users & Companies > Users**, open your own user,
   and add yourself to the **Otomater AI / Administrator** group (module
   install intentionally does not auto-assign this, since Odoo 19 changed
   how `res.groups` <-> `res.users` membership is set from data files -
   assigning it in XML with the old `users` field now fails on install).
5. Go to **Otomater AI > AI Settings > Providers**, create a provider
   record (pick OpenAI/Claude/Gemini/Ollama/Azure/OpenRouter), paste in
   your API key, and click **Test Connection**.
6. Mark exactly one provider **Default Provider** per company.
7. Go to **Otomater AI > AI Chat** and start chatting.

See `docs/INSTALLATION_GUIDE.md` for the full walkthrough including
Telegram/WhatsApp setup.

## Provider notes

- **OpenAI / OpenRouter**: just needs an API key. Model defaults to
  `gpt-4o-mini` / `openai/gpt-4o-mini` if left blank.
- **Claude (Anthropic)**: needs an API key. Model defaults to
  `claude-sonnet-4-6` if left blank.
- **Gemini**: needs an API key. Model defaults to `gemini-2.0-flash`.
- **Azure OpenAI**: `API Base URL` must be the full deployment endpoint,
  e.g. `https://<resource>.openai.azure.com/openai/deployments/<deployment>`.
  Set `API Version` (defaults to `2024-06-01`).
- **Ollama**: no API key needed. Set `API Base URL` to your Ollama host
  (defaults to `http://localhost:11434`) and `Model` to whatever you've
  pulled locally (e.g. `llama3.1`).

## Documentation set

Full docs live under `docs/`:
- `INSTALLATION_GUIDE.md`
- `DEVELOPER_GUIDE.md`
- `ADMINISTRATOR_GUIDE.md`
- `USER_MANUAL.md`
- `API_REFERENCE.md`

## Validation

Run the standard suite validation before every delivery:

```bash
python3 erp_tooling/validate_odoo19_module.py otomater_ai
python3 erp_tooling/check_forward_refs.py otomater_ai
```
