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