# -*- coding: utf-8 -*-
"""
Shared "channel bridge" logic for Telegram and WhatsApp (Phase 5).

Both ai.telegram.user and ai.whatsapp.user carry the same three fields
(user_id, conversation_id, awaiting_pending_action_id) so a single
function can drive both channels without duplicating the command
parsing / confirmation-flow logic. Everything here ultimately calls the
exact same ai.conversation.action_send_message() used by web chat and the
REST API, so an incoming Telegram/WhatsApp message goes through the same
planner, tool execution, and confirmation gate as everywhere else -
there's no separate, less-secure code path for chat channels.
"""

HELP_TEXT = (
    "Commands:\n"
    "/help - show this message\n"
    "/report - summary report\n"
    "/leave - leave balance & pending requests\n"
    "/attendance - today's attendance status\n"
    "/crm - your open CRM opportunities\n"
    "/stock - low or out-of-stock products\n"
    "/chat <message> - or just type anything to chat freely"
)

COMMAND_PROMPTS = {
    "/report": "Generate a summary report of key metrics.",
    "/leave": "Show me my leave balance and any pending leave requests.",
    "/attendance": "Show today's attendance status.",
    "/crm": "Show me my open CRM opportunities.",
    "/stock": "Show me products that are low or out of stock.",
}

CONFIRM_YES = {"yes", "y", "approve", "confirm"}
CONFIRM_NO = {"no", "n", "reject", "cancel"}


def handle_channel_message(channel_user, text):
    """channel_user: an ai.telegram.user or ai.whatsapp.user record
    (already resolved/linked to a res.users). Returns the reply text."""
    text = (text or "").strip()
    if not text:
        return HELP_TEXT

    scoped_env = channel_user.env(user=channel_user.user_id.id, su=False)

    if channel_user.awaiting_pending_action_id:
        pending = scoped_env["ai.pending.action"].browse(
            channel_user.awaiting_pending_action_id.id
        )
        lowered = text.lower()
        if lowered in CONFIRM_YES:
            result = pending.action_approve_rpc()
            channel_user.awaiting_pending_action_id = False
            return result["content"]
        if lowered in CONFIRM_NO:
            result = pending.action_reject_rpc()
            channel_user.awaiting_pending_action_id = False
            return result["content"]
        return (
            "There's a pending action waiting on your confirmation - "
            "reply YES to proceed or NO to cancel it first."
        )

    if text == "/help":
        return HELP_TEXT
    if text in COMMAND_PROMPTS:
        prompt = COMMAND_PROMPTS[text]
    elif text.lower().startswith("/chat "):
        prompt = text[6:].strip()
    else:
        prompt = text

    if not prompt:
        return HELP_TEXT

    conversation = channel_user.conversation_id
    if conversation and conversation.exists():
        conversation = conversation.with_env(scoped_env)
    else:
        conversation = scoped_env["ai.conversation"].create(
            {"user_id": channel_user.user_id.id}
        )
        channel_user.conversation_id = conversation.id

    try:
        message = conversation.action_send_message(prompt)
    except ValueError as exc:
        return str(exc)

    reply = message.content or message.error_message or ""
    if message.message_type == "confirmation" and message.pending_action_id:
        channel_user.awaiting_pending_action_id = message.pending_action_id.id
        reply = (reply + "\n\nReply YES to confirm or NO to cancel.").strip()
    return reply or "(no reply)"
