from datetime import timedelta

from odoo import api, fields, models


class AccountLoanLine(models.Model):
    _inherit = "account.loan.line"

    payment_state = fields.Selection(
        [
            ("pending", "Pendiente"),
            ("overdue", "En Mora"),
            ("paid", "Pagada"),
        ],
        string="Estado de Cobro",
        compute="_compute_payment_state",
        store=True,
        help="Pagada = tiene asientos generados. En Mora = fecha vencida sin pago.",
    )
    days_overdue = fields.Integer(
        string="Días de Mora",
        compute="_compute_payment_state",
        store=True,
    )
    color = fields.Integer(
        string="Color Calendario",
        compute="_compute_color",
    )
    partner_phone = fields.Char(
        related="partner_id.mobile",
        string="Celular Deudor",
    )
    send_reminder_ok = fields.Boolean(
        string="Puede Enviar Recordatorio",
        compute="_compute_send_reminder_ok",
        help="Disponible si la cuota está en mora, vence hoy, o vence mañana.",
    )

    @api.depends("payment_state", "date")
    def _compute_send_reminder_ok(self):
        today = fields.Date.context_today(self)
        tomorrow = today + timedelta(days=1)
        for line in self:
            line.send_reminder_ok = line.payment_state == "overdue" or line.date in (
                today,
                tomorrow,
            )

    def _build_whatsapp_reminder_message(self):
        self.ensure_one()
        amount = "{:,.2f}".format(self.payment_amount)
        currency = self.currency_id.symbol or ""
        fecha = self.date.strftime("%d/%m/%Y") if self.date else ""
        deudor = self.partner_id.name or ""
        prestamo = self.loan_id.name or ""
        if self.payment_state == "overdue":
            return (
                "Hola {deudor}, te recordamos que tu pago de {currency}{amount} "
                "correspondiente al préstamo {prestamo} está vencido desde el {fecha} "
                "({dias} días de mora). Por favor coordina tu pago a la brevedad. "
                "Gracias.".format(
                    deudor=deudor,
                    currency=currency,
                    amount=amount,
                    prestamo=prestamo,
                    fecha=fecha,
                    dias=self.days_overdue,
                )
            )
        return (
            "Hola {deudor}, te recordamos que tienes un pago de {currency}{amount} "
            "del préstamo {prestamo} programado para el {fecha}. ¡Gracias por tu "
            "puntualidad!".format(
                deudor=deudor,
                currency=currency,
                amount=amount,
                prestamo=prestamo,
                fecha=fecha,
            )
        )

    def action_open_whatsapp_reminder(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Recordatorio de Pago",
            "res_model": "gc.loans.whatsapp.reminder",
            "view_mode": "form",
            "target": "new",
            "context": {"default_loan_line_id": self.id},
        }

    @api.depends("date", "move_ids")
    def _compute_payment_state(self):
        today = fields.Date.context_today(self)
        for line in self:
            if line.move_ids:
                line.payment_state = "paid"
                line.days_overdue = 0
            elif line.date and line.date < today:
                line.payment_state = "overdue"
                line.days_overdue = (today - line.date).days
            else:
                line.payment_state = "pending"
                line.days_overdue = 0

    @api.depends("payment_state")
    def _compute_color(self):
        color_map = {"pending": 4, "overdue": 1, "paid": 10}
        for line in self:
            line.color = color_map.get(line.payment_state, 4)

    @api.model
    def _cron_refresh_payment_states(self):
        """Refresca payment_state para cuotas sin pago, activas.
        Necesario porque el compute depende de 'today', que no dispara
        invalidación automática en campos stored.
        """
        lines = self.search(
            [
                ("loan_state", "=", "posted"),
                ("move_ids", "=", False),
            ]
        )
        lines._compute_payment_state()