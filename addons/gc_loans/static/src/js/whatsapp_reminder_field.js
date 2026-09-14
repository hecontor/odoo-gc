/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useService } from "@web/core/utils/hooks";
import { Component } from "@odoo/owl";

class WhatsappReminderButtonField extends Component {
    static template = "gc_loans.WhatsappReminderButtonField";
    static props = { ...standardFieldProps };

    setup() {
        this.action = useService("action");
    }

    async onClick(ev) {
        // Evita que el clic se propague al popover/celda del calendario
        // y dispare su propio comportamiento (abrir edición, cerrar, etc).
        ev.stopPropagation();
        ev.preventDefault();
        // doActionButton es el mismo servicio que usan los botones nativos
        // type="object" — normaliza correctamente la acción devuelta por
        // el método Python (a diferencia de llamar orm.call + doAction a mano).
        await this.action.doActionButton({
            resModel: "account.loan.line",
            resId: this.props.record.resId,
            name: "action_open_whatsapp_reminder",
            type: "object",
        });
    }
}

registry.category("fields").add("gc_whatsapp_reminder_button", {
    component: WhatsappReminderButtonField,
});