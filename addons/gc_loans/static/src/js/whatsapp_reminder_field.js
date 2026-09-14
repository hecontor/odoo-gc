/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { Component } from "@odoo/owl";

class WhatsappReminderButtonField extends Component {
    static template = "gc_loans.WhatsappReminderButtonField";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
    }

    async onClick(ev) {
        // Evita que el clic se propague al popover/celda del calendario
        // y dispare su propio comportamiento (abrir edición, cerrar, etc).
        ev.stopPropagation();
        ev.preventDefault();
        const action = await this.orm.call(
            "account.loan.line",
            "action_open_whatsapp_reminder",
            [[this.props.record.resId]]
        );
        this.action.doAction(action);
    }
}

registry.category("fields").add("gc_whatsapp_reminder_button", {
    component: WhatsappReminderButtonField,
});
