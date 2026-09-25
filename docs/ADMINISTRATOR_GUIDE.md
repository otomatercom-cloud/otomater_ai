# Otomater AI - Administrator Guide

## Security groups

- **Otomater AI / User** - AI Chat, AI Conversations (own only), Pending
  Actions (own only), Prompt Library, Knowledge Base (read/create/write),
  API Keys (own only), My Telegram/My WhatsApp (own only).
- **Otomater AI / Administrator** - everything above plus AI Settings
  (Providers, Agents, Scheduled Agents, Audit Logs, Telegram Bot,
  WhatsApp Business).

Assign these under **Settings > Users & Companies > Users**. The
Administrator group is intentionally not auto-assigned to anyone during
install - assign it explicitly to whoever should configure providers and
review audit logs.

## The confirmation gate is your main safety control

Every action that creates, updates, deletes, calls a method, or runs a
server action is held in **Otomater AI > Pending Actions** until a human
approves it - in chat, over Telegram/WhatsApp (reply YES/NO), or via the
REST API's `/confirm` endpoint. There is no configuration flag to disable
this and let the AI auto-execute writes - that's by design. If you see an
unexpected pending action, you can always **Reject** it with zero
side effects.

Scheduled Agents (recurring background prompts) go through the exact
same gate - a scheduled prompt that proposes a destructive action creates
a pending action and (if recipients are configured) notifies them, but
it never executes unattended.

## Reviewing activity

- **Otomater AI > Pending Actions** - anything awaiting confirmation, or
  already resolved (approved/rejected/error), across all users.
- **Otomater AI > AI Settings > Audit Logs** - every chat reply, read
  tool call, and write tool call, with tokens/cost/execution
  time/status. Immutable (cannot be edited or deleted, even by admins -
  enforced at both the model level and the access-rights level).

## Cost control

Each `ai.provider` has `cost_per_1k_input`/`cost_per_1k_output` (fill
these in from your provider's published pricing) so the Dashboard and
Audit Log can show real cost figures, not just token counts. There is no
hard spending cap built in yet - if you need one, the cleanest place to
add it is a `@api.constrains` or a check at the top of
`ai.conversation.action_send_message()` comparing a rolling sum from
`ai.audit.log` against a configured limit.

## Multi-company

`ai.provider`, `ai.conversation`, and `ai.knowledge.document` all carry a
`company_id`. Provider/embedding-provider lookups
(`get_default_provider`/`get_default_embedding_provider`) filter by the
requesting user's company. If you run multiple companies with different
providers, create one `ai.provider` record per company and mark the
right one default/embedding-default in each.

## Revoking access

- **API Keys**: deactivate or delete the `ai.api.key` record under
  **Otomater AI > API Keys** - takes effect immediately (no caching).
- **Telegram/WhatsApp**: the user (or an admin, since admins see all
  records) can click **Unlink** on their `ai.telegram.user` /
  `ai.whatsapp.user` record. The chat_id/wa_number is cleared but the
  record and its `link_code` history stay for audit purposes.
- **A specific provider**: uncheck Active on the `ai.provider` record -
  in-flight requests using it will fail cleanly with a clear error
  rather than silently falling back to another provider.

## Backups and data retention

`ai.audit.log`, `ai.message`, and `ai.knowledge.chunk` will grow
indefinitely with usage. There's no automatic pruning built in - if you
need retention limits, a scheduled server action calling `unlink()` on
old records past a cutoff date is the standard Odoo pattern (note:
`ai.audit.log.unlink()` is blocked by design for immutability - if you
genuinely need retention pruning there, that's a deliberate exception to
carve out in a future customization, not something to route around).
