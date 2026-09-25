/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, useState, onWillStart } from "@odoo/owl";

export class OtomaterAiDashboard extends Component {
    static template = "otomater_ai.DashboardComponent";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.state = useState({
            loading: true,
            data: {
                total_requests: 0,
                today_requests: 0,
                today_conversations: 0,
                active_users: 0,
                avg_response_time: 0,
                total_tokens: 0,
                total_cost: 0,
                success_rate: 0,
                failed_requests: 0,
            },
        });

        onWillStart(async () => {
            this.state.data = await this.orm.call(
                "ai.audit.log",
                "get_dashboard_data",
                []
            );
            this.state.loading = false;
        });
    }
}

registry.category("actions").add("otomater_ai.dashboard", OtomaterAiDashboard);
