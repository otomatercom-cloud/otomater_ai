# Otomater AI - User Manual

## Chatting with the AI

Go to **Otomater AI > AI Chat**. Type a question or request and press
Enter (Shift+Enter for a new line). A small label above each reply shows
which specialized agent answered (HR Agent, CRM Agent, etc.) - you don't
need to pick one yourself, it's chosen automatically based on what you
asked.

Examples that just answer directly:
- "What's our leave policy for probation employees?" (if it's in the
  Knowledge Base)
- "How many leave requests are pending?"
- "Show me the last 10 sales orders."

Examples that ask for confirmation first:
- "Create a contact named Rahul Menon, email rahul@example.com"
- "Mark invoice INV/2026/0042 as paid"

For these, you'll see **Approve** / **Reject** buttons under the AI's
reply - nothing happens until you click Approve.

## Prompt Library

**Otomater AI > Prompt Library** has ready-made prompts grouped by
department. Click **Use in Chat** on any of them to open AI Chat with
that prompt already typed in - review or edit it, then send.

## Pending Actions

**Otomater AI > Pending Actions** lists anything you've asked the AI to
do that's still waiting for your confirmation, plus your past
approvals/rejections. If you approved something by mistake, there's no
undo here - use the normal Odoo screens to reverse the change, the same
as you would for anything else.

## API Keys

If you (or someone on your team) wants to call Otomater AI from outside
Odoo - a script, another app, etc. - go to **Otomater AI > API Keys**,
click New, give it a name, and save. The key appears once; copy it
somewhere safe. A key only ever does what you personally could do in
Odoo - it's not a separate, more powerful account.

## Telegram

1. Go to **Otomater AI > My Telegram**, click **Generate Link Code**.
2. Open Telegram, find the bot your admin set up, send `/link <code>`
   using the code you just got.
3. From then on, just message the bot normally. Useful shortcuts:
   `/help`, `/report`, `/leave`, `/attendance`, `/crm`, `/stock`.
4. If the AI asks for confirmation, reply `YES` or `NO`.

## WhatsApp

Same idea as Telegram:
1. **Otomater AI > My WhatsApp** > **Generate Link Code**.
2. Send `LINK <code>` to your company's WhatsApp Business number.
3. Chat normally from there; reply `YES`/`NO` to confirm proposed
   actions.

## Dark mode

AI Chat and the Dashboard follow whatever light/dark setting you already
have set for Odoo itself - no separate toggle needed.
