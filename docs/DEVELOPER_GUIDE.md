# Otomater AI - Developer Guide

## Architecture at a glance

```
models/
  provider_adapter.py       Plain-Python LLM + embedding HTTP adapters (no ORM)
  ai_knowledge_service.py   Plain-Python text extraction/chunking/similarity (no ORM)
  ai_channel_service.py     Shared Telegram/WhatsApp message-handling logic (no ORM)
  ai_provider.py            ai.provider - LLM + embedding provider config
  ai_introspection.py       ai.introspection - discovers installed models at runtime
  ai_tool_executor.py       ai.tool.executor - generic ORM tool dispatch (the security boundary)
  ai_agent.py               ai.agent - specialized personas + keyword delegation
  ai_pending_action.py      ai.pending.action - confirmation gate for destructive tools
  ai_conversation.py        ai.conversation - the planner loop (chat vs. tool call)
  ai_message.py             ai.message - one message in a conversation
  ai_audit_log.py           ai.audit.log - immutable audit trail
  ai_prompt.py              ai.prompt - Prompt Library
  ai_scheduled_agent.py     ai.scheduled.agent - recurring prompts via dynamic ir.cron
  ai_knowledge_chunk.py     ai.knowledge.chunk - embedded text chunk
  ai_knowledge_document.py  ai.knowledge.document - Knowledge Base source document
  ai_api_key.py             ai.api.key - REST API authentication
  ai_telegram_config.py     ai.telegram.config - bot token, send/poll/webhook-set
  ai_telegram_user.py       ai.telegram.user - per-user Telegram link + channel state
  ai_whatsapp_config.py     ai.whatsapp.config - Meta Cloud API config, send/receive
  ai_whatsapp_user.py       ai.whatsapp.user - per-user WhatsApp link + channel state

controllers/
  main.py        REST API (/otomater_ai/api/...)
  telegram.py    Telegram webhook
  whatsapp.py    WhatsApp webhook (verification + receive)

static/src/
  js/chat/chat_component.js         OWL client action: AI Chat
  js/dashboard/dashboard_component.js OWL client action: Dashboard
  xml/*.xml                         OWL templates for the above
  css/otomater_ai.css               Plain CSS (light + dark mode)
```

## The core request lifecycle (chat, REST API, Telegram, WhatsApp all use this)

1. A message arrives at `ai.conversation.action_send_message(content)`
   from one of four callers: the OWL chat widget (`action_send_message_rpc`
   over standard Odoo RPC), the REST API (`POST /otomater_ai/api/chat`),
   or a channel bridge (`ai_channel_service.handle_channel_message`, used
   by both Telegram and WhatsApp).
2. `ai.agent.find_best_agent()` picks a specialized persona by keyword
   overlap (no LLM call).
3. `ai.introspection.build_tool_context()` shortlists ~6-8 relevant,
   ACL-readable models for the current user, biased by the agent's
   keywords.
4. The provider is called once with a system prompt (persona + tool
   schema + shortlisted models) asking for a single JSON plan:
   `{"action", "model", "params", "message"}`.
5. If the action is a read-only tool (`search_records`, `count_records`,
   `read_record`, `search_knowledge`, `open_form`, `download_report`), it
   runs immediately via `ai.tool.executor.execute_tool()` and the
   formatted result is appended to the reply.
6. If the action is destructive (`create_record`, `update_record`,
   `delete_record`, `call_method`, `execute_server_action`), NOTHING
   executes yet - an `ai.pending.action` record is created describing
   what would happen, and the message is flagged
   `message_type='confirmation'`. Only `ai.pending.action._approve()`
   (triggered by the user clicking Approve, replying YES on
   Telegram/WhatsApp, or `POST /otomater_ai/api/confirm`) actually calls
   the executor.
7. Every round trip is logged to `ai.audit.log` (immutable).

**Everything in `ai.tool.executor` runs as `self.env.user`, never sudo.**
This is the single security invariant the whole module depends on: the AI
can never do more than the requesting user could already do by hand. If
you add a new tool, do not sudo it - if it needs elevated access, that's
a sign it should be a destructive tool requiring confirmation, not an
automatic one.

## Adding a new LLM provider

1. Add a `call_<name>(config, messages)` function to
   `models/provider_adapter.py` following the existing ones' shape
   (return `{"content", "tokens_input", "tokens_output", "raw"}`, raise
   `ProviderError` on failure).
2. Register it in the `ADAPTERS` dict.
3. Add the selection value to `ai.provider.code`.
4. (Optional) Add a matching `call_<name>_embedding` + register in
   `EMBEDDING_ADAPTERS` if the provider offers embeddings.

No other file needs to change - `ai.provider.call()` /
`ai.provider.get_embedding()` dispatch generically by `code`.

## Adding a new tool

1. Add a method to `AiToolExecutor` in `models/ai_tool_executor.py` with
   plain keyword arguments (whatever `execute_tool` will pass as
   `**params`). Keep it running as `self.env.user`.
2. Add its name to `READ_ONLY_TOOLS` or `DESTRUCTIVE_TOOLS` (never both).
3. Document its param shape in `PLANNER_SYSTEM_PROMPT` in
   `models/ai_conversation.py` so the LLM knows how to call it.
4. If it's read-only, add a formatting case to `_format_read_result()` in
   the same file so the chat reply looks reasonable.

That's it - the REST API's `/execute` endpoint and the destructive-tool
confirmation flow both key off `ALL_TOOLS`/`READ_ONLY_TOOLS`/
`DESTRUCTIVE_TOOLS`, so a new tool is automatically usable everywhere.

## Adding a new specialized agent

Add an `ai.agent` record (via UI or a data file) with `code`,
`keywords`, and `description` (persona text). No Python changes needed -
`find_best_agent()` and the planner prompt builder both work generically
off whatever `ai.agent` records exist.

## Testing changes locally

There's no formal automated test suite in this module yet (Phase 6+ if
you want one - `odoo.tests.TransactionCase` is the standard approach for
Odoo). In the meantime:

```bash
python3 erp_tooling/validate_odoo19_module.py otomater_ai
python3 erp_tooling/check_forward_refs.py otomater_ai
odoo-bin -c odoo.conf -d your_db -u otomater_ai --stop-after-init
```

Then exercise the chat widget with a read query, a write query (check
the confirmation actually blocks execution until approved), and a
Knowledge Base search if you have documents indexed.
