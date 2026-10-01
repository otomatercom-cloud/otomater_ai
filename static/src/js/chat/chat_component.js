/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { session } from "@web/session";
import { Component, useState, useRef, onMounted, onWillStart, markup } from "@odoo/owl";

function escapeHtml(str) {
    return String(str ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function inlineFmt(escaped) {
    return escaped.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
}

/** Safe mini-markdown: paragraphs, **bold**, bullet lists and tables.
 * Input is HTML-escaped first, so message text can never inject markup. */
export function renderMarkdown(text) {
    const lines = String(text ?? "").split("\n");
    const html = [];
    let i = 0;
    while (i < lines.length) {
        const line = lines[i].trim();
        if (line.startsWith("|") && line.endsWith("|")) {
            const rows = [];
            while (i < lines.length && lines[i].trim().startsWith("|")) {
                rows.push(lines[i].trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim()));
                i++;
            }
            const sep = rows.length > 1 && rows[1].every((c) => /^:?-+:?$/.test(c));
            const head = rows[0];
            const body = rows.slice(sep ? 2 : 1);
            html.push('<div class="o_otomater_ai_table_wrap"><table class="o_otomater_ai_table"><thead><tr>' +
                head.map((c) => `<th>${inlineFmt(escapeHtml(c))}</th>`).join("") +
                "</tr></thead><tbody>" +
                body.map((r) => "<tr>" + r.map((c) => `<td>${inlineFmt(escapeHtml(c))}</td>`).join("") + "</tr>").join("") +
                "</tbody></table></div>");
            continue;
        }
        if (line.startsWith("- ")) {
            const items = [];
            while (i < lines.length && lines[i].trim().startsWith("- ")) {
                items.push(`<li>${inlineFmt(escapeHtml(lines[i].trim().slice(2)))}</li>`);
                i++;
            }
            html.push(`<ul class="o_otomater_ai_list">${items.join("")}</ul>`);
            continue;
        }
        if (line) {
            html.push(`<p>${inlineFmt(escapeHtml(line))}</p>`);
        }
        i++;
    }
    return markup(html.join(""));
}

export class OtomaterAiChat extends Component {
    static template = "otomater_ai.ChatComponent";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
        this.inputRef = useRef("chatInput");
        this.messagesRef = useRef("messagesContainer");

        this.state = useState({
            conversationId: null,
            conversationName: "",
            messages: [],
            draft: "",
            sending: false,
        });

        this.currentUserName = session.name || "";

        onWillStart(async () => {
            const conv = await this.orm.call(
                "ai.conversation",
                "get_or_create_open_conversation",
                [false]
            );
            this.state.conversationId = conv[0] ? conv[0] : conv;
        });

        const draftFromPrompt = this.props.action?.params?.draft;
        if (draftFromPrompt) {
            this.state.draft = draftFromPrompt;
        }

        onMounted(() => {
            if (this.inputRef.el) {
                this.inputRef.el.focus();
            }
        });
    }

    renderContent(msg) {
        return renderMarkdown(msg.content);
    }

    hasTable(msg) {
        return /^\s*\|.*\|\s*$/m.test(msg.content || "");
    }

    scrollToBottom() {
        const el = this.messagesRef.el;
        if (el) {
            el.scrollTop = el.scrollHeight;
        }
    }

    onInputKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey) {
            ev.preventDefault();
            this.sendMessage();
        }
    }

    async sendMessage() {
        const content = this.state.draft.trim();
        if (!content || this.state.sending) {
            return;
        }
        this.state.draft = "";
        this.state.messages.push({
            id: `local-${Date.now()}`,
            role: "user",
            content,
            status: "success",
            messageType: "text",
            pendingActionId: false,
            resolved: true,
        });
        this.state.sending = true;
        this.scrollToBottom();

        try {
            const result = await this.orm.call(
                "ai.conversation",
                "action_send_message_rpc",
                [this.state.conversationId, content]
            );
            this.state.conversationName = result.conversation_name;
            this.state.messages.push({
                id: result.message.id,
                role: result.message.role,
                content:
                    result.message.status === "error"
                        ? result.message.error_message ||
                          "The AI provider returned an error."
                        : result.message.content,
                status: result.message.status,
                messageType: result.message.message_type,
                pendingActionId: result.message.pending_action_id,
                agentName: result.message.agent_name,
                resolved: false,
            });
        } catch (error) {
            this.notification.add(
                error.message?.data?.message || "Failed to reach the AI provider.",
                { type: "danger" }
            );
        } finally {
            this.state.sending = false;
            this.scrollToBottom();
        }
    }
    async resolvePending(msg, approve) {
        if (msg.resolving || msg.resolved) {
            return;
        }
        msg.resolving = true;
        try {
            const method = approve ? "action_approve_rpc" : "action_reject_rpc";
            const resultMessage = await this.orm.call(
                "ai.pending.action",
                method,
                [msg.pendingActionId]
            );
            msg.resolved = true;
            this.state.messages.push({
                id: resultMessage.id,
                role: resultMessage.role,
                content: resultMessage.content,
                status: resultMessage.status,
                messageType: "text",
                pendingActionId: false,
                resolved: true,
            });
        } catch (error) {
            this.notification.add(
                error.message?.data?.message || "Failed to resolve the pending action.",
                { type: "danger" }
            );
        } finally {
            msg.resolving = false;
            this.scrollToBottom();
        }
    }

    approvePending(msg) {
        return this.resolvePending(msg, true);
    }

    rejectPending(msg) {
        return this.resolvePending(msg, false);
    }
}

registry.category("actions").add("otomater_ai.chat", OtomaterAiChat);
