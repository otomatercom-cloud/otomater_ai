/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { session } from "@web/session";
import { Component, useState, useRef, onMounted, onWillStart } from "@odoo/owl";

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
