# Otomater AI - Installation Guide

## Requirements

- Odoo 19.0 Community Edition
- Python packages already required by core Odoo: `requests` (used for all
  provider/Telegram/WhatsApp HTTP calls - already an Odoo dependency, no
  extra install needed)
- Optional, only if you plan to ingest those file types into the
  Knowledge Base:
  - `pip install PyPDF2 --break-system-packages` (PDF)
  - `pip install python-docx --break-system-packages` (DOCX)
  - `pip install openpyxl --break-system-packages` (XLSX/XLS)
  - `pip install beautifulsoup4 --break-system-packages` (nicer URL
    extraction - a regex-based fallback works without it)

## Fresh install

1. Copy the `otomater_ai` folder into your custom addons path, e.g.
   `E:\odoo19\custom-addons\otomater_ai`.
2. Restart the Odoo service.
3. Log in as an administrator, enable developer mode, go to **Apps**,
   click **Update Apps List**, then search for and install **Otomater
   AI**.
4. Go to **Settings > Users & Companies > Users**, open your own user,
   and add yourself to the **Otomater AI / Administrator** group (this is
   intentionally not auto-assigned - see the Administrator Guide for
   why).
5. Go to **Otomater AI > AI Settings > Providers**, add at least one LLM
   provider and click **Test Connection**. Mark it **Default Provider**.
6. (Optional) Mark one provider **Use for Embeddings** if you plan to use
   the Knowledge Base.
7. Go to **Otomater AI > AI Chat** and send a message.

## Upgrading between phases

Every phase after Phase 1 is an **in-place upgrade** of the same module,
not a fresh install - each phase only adds models/fields/menus, it never
renames or removes anything from an earlier phase.

```bash
# stop Odoo first, then:
odoo-bin -c odoo.conf -d your_db -u otomater_ai --stop-after-init
# restart Odoo
```

If you're on an older phase and jumping straight to this version, a
single `-u otomater_ai` run picks up every intermediate migration in one
pass - there's nothing sequential you need to do phase-by-phase.

## Verifying the install

Run the module's own validation suite (matches the `erp_tooling`
standard used across this suite of modules):

```bash
python3 erp_tooling/validate_odoo19_module.py otomater_ai
python3 erp_tooling/check_forward_refs.py otomater_ai
```

Both should report zero violations.

## Telegram setup (optional)

1. Create a bot via [@BotFather](https://t.me/BotFather) on Telegram,
   copy the token it gives you.
2. Go to **Otomater AI > AI Settings > Telegram Bot**, create a record,
   paste the token.
3. If your Odoo instance has a public HTTPS URL, click **Set Webhook**.
   If it doesn't (e.g. local dev on `localhost:8019`), instead go to
   **Settings > Technical > Scheduled Actions**, find "Otomater AI: Poll
   Telegram Updates", and activate it.
4. Each user goes to **Otomater AI > My Telegram**, clicks **Generate
   Link Code**, and sends `/link <code>` to the bot from their own
   Telegram account.

## WhatsApp setup (optional)

1. Set up a WhatsApp Business Cloud API app in
   [Meta's developer console](https://developers.facebook.com/), get a
   Phone Number ID and a permanent access token.
2. Go to **Otomater AI > AI Settings > WhatsApp Business**, create a
   record with those values plus a verify token of your choosing.
3. In Meta's dashboard, set the webhook URL to
   `https://<your public domain>/otomater_ai/whatsapp/webhook` and the
   verify token to match what you entered in step 2.
4. Each user goes to **Otomater AI > My WhatsApp**, clicks **Generate
   Link Code**, and sends `LINK <code>` to your WhatsApp Business number.

Both Telegram and WhatsApp **require a publicly reachable HTTPS URL** to
receive webhooks - Telegram's polling cron is the practical workaround
for local/dev environments; WhatsApp does not offer a polling
alternative, so a public URL (or a tunneling tool like ngrok for testing)
is required for WhatsApp.
