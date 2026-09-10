# Copyright 2018 Creu Blanca
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import logging
import math
from datetime import datetime

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)
try:
    import numpy_financial
except (OSError, ImportError) as err:
    _logger.debug(err)


class AccountLoan(models.Model):
    _name = "account.loan"
    _description = "Loan"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    def _default_company(self):
        return self.env.company

    name = fields.Char(
        copy=False,
        required=True,
        default="/",
    )
    partner_id = fields.Many2one(
        "res.partner",
        required=True,
        string="Deudor",
        help="Persona o empresa que recibe el préstamo.",
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=_default_company,
    )
    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("posted", "Contabilizado"),
            ("cancelled", "Cancelado"),
            ("closed", "Cerrado"),
        ],
        required=True,
        copy=False,
        default="draft",
    )
    line_ids = fields.One2many(
        "account.loan.line",
        readonly=True,
        inverse_name="loan_id",
        copy=False,
    )
    periods = fields.Integer(
        required=True,
        string="Número de Cuotas",
        help="Cantidad de cuotas en las que se pagará el préstamo",
    )
    method_period = fields.Integer(
        string="Longitud del Período (meses)",
        default=1,
        help="Meses entre cada pago. Solo aplica para Cuota Fija y Solo Intereses.",
        required=True,
    )
    start_date = fields.Date(
        string="Fecha de Inicio",
        help="Fecha desde la que se calculan los pagos",
        copy=False,
    )
    rate = fields.Float(
        required=True,
        default=0.0,
        digits=(8, 6),
        string="Interés Mensual (%)",
        help="Tasa de interés mensual aplicada al préstamo",
        tracking=True,
    )
    rate_period = fields.Float(
        compute="_compute_rate_period",
        digits=(8, 6),
        string="Tasa por Período",
        help="Tasa real aplicada en cada período",
    )
    rate_type = fields.Selection(
        [("napr", "Nominal APR"), ("ear", "EAR"), ("real", "Tasa Real")],
        required=True,
        help="Método de cálculo de la tasa aplicada",
        default="real",
    )
    # Campo principal de tipo de préstamo visible al usuario
    method = fields.Selection(
        [
            ("stable_fixed", "Cuotas Fijas Estables (G&C)"),
            ("fixed", "Cuota Fija (Amortización)"),
            ("interest", "Solo Intereses"),
        ],
        string="Tipo de Préstamo",
        required=True,
        default="stable_fixed",
        help="Método de cálculo de las cuotas.",
    )
    payment_frequency = fields.Selection(
        [
            ("weekly", "Semanal"),
            ("biweekly", "Quincenal"),
            ("monthly", "Mensual"),
        ],
        string="Frecuencia de Pago",
        default="monthly",
        help="Solo aplica para Cuotas Fijas Estables.",
    )
    # loan_type se mantiene para compatibilidad con la lógica interna del módulo
    loan_type = fields.Selection(
        [
            ("fixed-annuity", "Fixed Annuity"),
            ("fixed-annuity-begin", "Fixed Annuity Begin"),
            ("fixed-principal", "Fixed Principal"),
            ("interest", "Only interest"),
        ],
        required=True,
        default="fixed-annuity",
    )
    fixed_amount = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_fixed_amount",
    )
    fixed_loan_amount = fields.Monetary(
        currency_field="currency_id",
        readonly=True,
        copy=False,
        default=0,
    )
    fixed_periods = fields.Integer(
        readonly=True,
        copy=False,
        default=0,
    )
    loan_amount = fields.Monetary(
        currency_field="currency_id",
        required=True,
        string="Importe Prestado",
    )
    residual_amount = fields.Monetary(
        currency_field="currency_id",
        default=0.0,
        required=True,
        help="Importe residual al final del préstamo (usado en leasing).",
    )
    round_on_end = fields.Boolean(
        help="Si está marcado, las diferencias se aplican en el último período.",
    )
    payment_on_first_period = fields.Boolean(
        string="Pago en el Primer Período",
        help="Si está marcado, el primer pago es en la fecha de inicio.",
    )
    currency_id = fields.Many2one(
        "res.currency",
        compute="_compute_currency",
        readonly=True,
    )
    journal_type = fields.Char(compute="_compute_journal_type")
    journal_id = fields.Many2one(
        "account.journal",
        domain="[('company_id', '=', company_id),('type', '=', journal_type)]",
        required=True,
        string="Diario",
    )
    short_term_loan_account_id = fields.Many2one(
        "account.account",
        domain="[('company_id', '=', company_id)]",
        string="Cuenta por Cobrar (CP)",
        help="Cuenta de préstamos por cobrar a corto plazo",
        required=True,
        default=lambda self: self._get_default_loan_account(),
    )
    long_term_loan_account_id = fields.Many2one(
        "account.account",
        string="Cuenta por Cobrar (LP)",
        help="Cuenta de préstamos por cobrar a largo plazo",
        domain="[('company_id', '=', company_id)]",
    )
    interest_expenses_account_id = fields.Many2one(
        "account.account",
        domain="[('company_id', '=', company_id)]",
        string="Cuenta de Ingresos por Intereses",
        help="Cuenta donde se registran los intereses cobrados",
        required=True,
        default=lambda self: self._get_default_interest_account(),
    )
    is_leasing = fields.Boolean()
    leased_asset_account_id = fields.Many2one(
        "account.account",
        domain="[('company_id', '=', company_id)]",
    )
    product_id = fields.Many2one(
        "product.product",
        string="Producto del Préstamo",
    )
    interests_product_id = fields.Many2one(
        "product.product",
        string="Producto de Intereses",
    )
    move_ids = fields.One2many("account.move", copy=False, inverse_name="loan_id")
    move_count = fields.Integer(compute="_compute_move_count")
    pending_principal_amount = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_total_amounts",
        string="Capital Pendiente",
    )
    payment_amount = fields.Monetary(
        currency_field="currency_id",
        string="Total Cobrado",
        compute="_compute_total_amounts",
    )
    interests_amount = fields.Monetary(
        currency_field="currency_id",
        string="Total Intereses Cobrados",
        compute="_compute_total_amounts",
    )
    post_invoice = fields.Boolean(
        default=True, help="Las facturas se contabilizan automáticamente."
    )

    _sql_constraints = [
        ("name_uniq", "unique(name, company_id)", "El nombre del préstamo debe ser único"),
    ]

    # ------------------------------------------------------------------
    # Onchange
    # ------------------------------------------------------------------

    @api.onchange("method")
    def _onchange_method(self):
        """Sync loan_type with method and set sensible defaults."""
        if self.method == "stable_fixed":
            self.loan_type = "fixed-annuity"
            self.rate_type = "real"
        elif self.method == "fixed":
            self.loan_type = "fixed-annuity"
        elif self.method == "interest":
            self.loan_type = "interest"

    @api.onchange("rate")
    def _onchange_rate_warning(self):
        if self.state != "draft":
            return {
                "warning": {
                    "title": _("Cambio de Tasa"),
                    "message": _(
                        "Modificaste la tasa de interés. Haz clic en 'Calcular Elementos' "
                        "para actualizar las cuotas. Los cambios manuales en las líneas se perderán."
                    ),
                }
            }

    @api.onchange("line_ids")
    def _onchange_line_ids_draft_manual(self):
        self.line_ids = self.line_ids.sorted(key=lambda line: line.sequence)
        previous_pending_principal = 0
        previous_principal_amount = 0
        for line in self.line_ids:
            if line.sequence == 1:
                line.pending_principal_amount = line.loan_id.loan_amount
            else:
                line.pending_principal_amount = (
                    previous_pending_principal - previous_principal_amount
                )
            previous_pending_principal = line.pending_principal_amount
            previous_principal_amount = line.principal_amount

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------

    @api.depends("move_ids")
    def _compute_move_count(self):
        for item in self:
            item.move_count = len(item.move_ids)

    @api.depends("line_ids", "currency_id", "loan_amount")
    def _compute_total_amounts(self):
        for record in self:
            lines = record.line_ids.filtered(lambda r: r.move_ids)
            record.interests_amount = sum(lines.mapped("interests_amount")) or 0.0
            principal_paid = sum(lines.mapped("principal_amount")) or 0.0
            record.payment_amount = sum(lines.mapped("payment_amount")) or 0.0
            record.pending_principal_amount = record.loan_amount - principal_paid

    @api.depends("rate_period", "fixed_loan_amount", "fixed_periods", "currency_id")
    def _compute_fixed_amount(self):
        for record in self:
            if record.loan_type == "fixed-annuity":
                try:
                    record.fixed_amount = -record.currency_id.round(
                        numpy_financial.pmt(
                            record._loan_rate() / 100,
                            record.fixed_periods,
                            record.fixed_loan_amount,
                            -record.residual_amount,
                        )
                    )
                except Exception:
                    record.fixed_amount = 0.0
            elif record.loan_type == "fixed-annuity-begin":
                try:
                    record.fixed_amount = -record.currency_id.round(
                        numpy_financial.pmt(
                            record._loan_rate() / 100,
                            record.fixed_periods,
                            record.fixed_loan_amount,
                            -record.residual_amount,
                            when="begin",
                        )
                    )
                except Exception:
                    record.fixed_amount = 0.0
            elif record.loan_type == "fixed-principal":
                record.fixed_amount = record.currency_id.round(
                    (record.fixed_loan_amount - record.residual_amount)
                    / record.fixed_periods
                    if record.fixed_periods
                    else 0.0
                )
            else:
                record.fixed_amount = 0.0

    @api.model
    def _compute_rate(self, rate, rate_type, method_period):
        """
        Returns the effective rate per period.
        napr: Nominal Annual Percentage Rate → divide by 12 then multiply by months
        ear: Effective Annual Rate → compound
        real: rate is already the per-period rate
        """
        if rate_type == "napr":
            return rate / 12.0 * method_period
        if rate_type == "ear":
            return math.pow(1 + rate / 100, method_period / 12) - 1
        return rate

    @api.depends("rate", "method_period", "rate_type", "method", "payment_frequency")
    def _compute_rate_period(self):
        for record in self:
            record.rate_period = record._loan_rate()

    def _loan_rate(self):
        """
        Devuelve la tasa efectiva por período de pago.

        - stable_fixed: siempre la tasa mensual directa (interés simple plano).
        - fixed + biweekly: tasa mensual dividida entre 2 (proporcional).
        - fixed + weekly:   tasa mensual dividida entre 4 (proporcional).
        - fixed + monthly:  usa _compute_rate con method_period.
        - interest:         igual que fixed monthly.
        """
        if self.method == "stable_fixed":
            return self.rate
        if self.method == "fixed":
            if self.payment_frequency == "biweekly":
                return self.rate / 2.0
            if self.payment_frequency == "weekly":
                return self.rate / 4.0
        return self._compute_rate(self.rate, self.rate_type, self.method_period)

    @api.depends("journal_id", "company_id")
    def _compute_currency(self):
        for rec in self:
            rec.currency_id = rec.journal_id.currency_id or rec.company_id.currency_id

    @api.depends("is_leasing")
    def _compute_journal_type(self):
        for record in self:
            if record.is_leasing:
                record.journal_type = "sale"
            else:
                record.journal_type = "general"

    @api.onchange("is_leasing")
    def _onchange_is_leasing(self):
        self.journal_id = self.env["account.journal"].search(
            [
                ("company_id", "=", self.company_id.id),
                ("type", "=", "sale" if self.is_leasing else "general"),
            ],
            limit=1,
        )
        self.residual_amount = 0.0

    @api.onchange("company_id")
    def _onchange_company(self):
        self._onchange_is_leasing()
        # Solo limpiar si no tienen valor aún, para no borrar defaults o selecciones manuales
        if not self.short_term_loan_account_id:
            self.short_term_loan_account_id = self._get_default_loan_account()
        if not self.interest_expenses_account_id:
            self.interest_expenses_account_id = self._get_default_interest_account()
        if not self.long_term_loan_account_id:
            self.long_term_loan_account_id = False

    # ------------------------------------------------------------------
    # Defaults
    # ------------------------------------------------------------------

    def _get_default_name(self, vals):
        return self.env["ir.sequence"].next_by_code("account.loan") or "/"

    @api.model
    def _get_default_loan_account(self):
        """
        11030205 - Otras Cuentas por Cobrar (Por cobrar)
        Rastrea el capital pendiente de la cartera de préstamos.
        Se acredita cuando se cobra cada cuota (reduce el saldo prestado).
        NO usar 11030201 porque esa es la cuenta del deudor (partner receivable).
        """
        account = self.env["account.account"].search(
            [("code", "=", "11030205"), ("company_id", "=", self.env.company.id)],
            limit=1,
        )
        return account.id if account else False

    @api.model
    def _get_default_interest_account(self):
        """
        42010300 - Intereses por Financiamientos (Ingreso)
        Registra el ingreso por intereses cobrados en cada cuota.
        Es una cuenta de INGRESO, no de activo.
        """
        account = self.env["account.account"].search(
            [("code", "=", "42010300"), ("company_id", "=", self.env.company.id)],
            limit=1,
        )
        return account.id if account else False

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "/") == "/":
                vals["name"] = self._get_default_name(vals)
            # Sync loan_type from method when creating
            method = vals.get("method", "stable_fixed")
            if "loan_type" not in vals:
                if method == "interest":
                    vals["loan_type"] = "interest"
                else:
                    vals["loan_type"] = "fixed-annuity"
        return super().create(vals_list)

    # ------------------------------------------------------------------
    # State transitions
    # ------------------------------------------------------------------

    def post(self):
        self.ensure_one()
        if not self.start_date:
            self.start_date = fields.Date.today()
        if not self.line_ids:
            self._compute_draft_lines()
        self.write({"state": "posted"})

    def close(self):
        self.write({"state": "closed"})

    def button_draft(self):
        for item in self:
            if item.state not in ("posted", "cancelled") or item.move_count > 0:
                raise UserError(
                    _(
                        "Solo se puede volver a borrador si el estado es "
                        "cancelado o contabilizado y no existen asientos contables."
                    )
                )
            item.state = "draft"

    # ------------------------------------------------------------------
    # Line computation
    # ------------------------------------------------------------------

    def compute_lines(self):
        self.ensure_one()
        if self.state == "draft":
            return self._compute_draft_lines()
        return self._compute_posted_lines()

    def _compute_posted_lines(self):
        """Recompute amounts of not-yet-processed lines (e.g. after rate change)."""
        # stable_fixed: amounts are fixed — nothing to recompute
        if self.method == "stable_fixed":
            return

        amount = self.loan_amount
        for line in self.line_ids.sorted("sequence"):
            if line.move_ids:
                amount = line.final_pending_principal_amount
            else:
                line.rate = self.rate_period
                line.pending_principal_amount = amount
                line._check_amount()
                amount -= line.payment_amount - line.interests_amount
        if self.long_term_loan_account_id:
            self._check_long_term_principal_amount()

    def _check_long_term_principal_amount(self):
        lines = self.line_ids.filtered(lambda r: not r.move_ids)
        amount = 0
        if not lines:
            return
        final_sequence = min(lines.mapped("sequence"))
        for line in lines.sorted("sequence", reverse=True):
            date = line.date + relativedelta(months=12)
            if self.state == "draft" or line.sequence != final_sequence:
                line.long_term_pending_principal_amount = sum(
                    self.line_ids.filtered(
                        lambda r, date=date: r.date >= date
                    ).mapped("principal_amount")
                )
            line.long_term_principal_amount = (
                line.long_term_pending_principal_amount - amount
            )
            amount = line.long_term_pending_principal_amount

    def _new_line_vals(self, sequence, date, amount):
        return {
            "loan_id": self.id,
            "sequence": sequence,
            "date": date,
            "pending_principal_amount": amount,
            "rate": self.rate_period,
        }

    def _compute_draft_lines(self):
        self.ensure_one()
        self.fixed_periods = self.periods
        self.fixed_loan_amount = self.loan_amount
        self.line_ids.unlink()

        amount = self.loan_amount
        date = self.start_date if self.start_date else datetime.today().date()
        initial_date = date

        # ------------------------------------------------------------------
        # CUOTAS FIJAS ESTABLES (G&C Flat Interest)
        # Interés simple sobre el capital original. La tasa es siempre mensual.
        # La frecuencia (semanal/quincenal/mensual) determina el delta de fechas
        # pero el interés se calcula sobre el total de meses del préstamo.
        # Ejemplo: 10,000 × 20% × 1 mes = 2,000 de interés total.
        #   - Mensual  (1 cuota):  1 × 12,000
        #   - Quincenal (2 cuotas): 2 × 6,000
        #   - Semanal   (4 cuotas): 4 × 3,000
        # ------------------------------------------------------------------
        if self.method == "stable_fixed":
            if self.payment_frequency == "weekly":
                delta = relativedelta(weeks=1)
                meses_totales = self.periods / 4.0
            elif self.payment_frequency == "biweekly":
                delta = relativedelta(days=15)
                meses_totales = self.periods / 2.0
            else:  # monthly
                delta = relativedelta(months=1)
                meses_totales = float(self.periods)

            if not self.payment_on_first_period:
                date = initial_date + delta
                initial_date = date

            # Interés total plano sobre el capital original
            interes_total = self.currency_id.round(
                self.loan_amount * (self.rate / 100.0) * meses_totales
            )
            capital_por_cuota = self.currency_id.round(self.loan_amount / self.periods)
            interes_por_cuota = self.currency_id.round(interes_total / self.periods)

            for i in range(1, self.periods + 1):
                # Última cuota: ajuste por redondeo para que cuadre exactamente
                if i == self.periods:
                    capital_esta_cuota = self.currency_id.round(amount)
                    interes_esta_cuota = self.currency_id.round(
                        interes_total
                        - interes_por_cuota * (self.periods - 1)
                    )
                else:
                    capital_esta_cuota = capital_por_cuota
                    interes_esta_cuota = interes_por_cuota

                cuota_esta = self.currency_id.round(capital_esta_cuota + interes_esta_cuota)

                line = self.env["account.loan.line"].create({
                    "loan_id": self.id,
                    "sequence": i,
                    "date": date,
                    "pending_principal_amount": self.currency_id.round(amount),
                    "rate": 0.0,  # Valor inicial; se recalcula tras escribir interests_amount
                })
                # Escribir todos los importes juntos para evitar conflictos
                # entre los compute encadenados de payment/principal/interests
                line.write({
                    "interests_amount": interes_esta_cuota,
                    "payment_amount": cuota_esta,
                    "principal_amount": capital_esta_cuota,
                })

                date = initial_date + delta * i
                amount = self.currency_id.round(amount - capital_esta_cuota)

        # ------------------------------------------------------------------
        # CUOTA FIJA AMORTIZACIÓN y SOLO INTERESES
        # Soporta mensual (method_period meses), quincenal y semanal.
        # La tasa por período se obtiene de _loan_rate() que ya divide
        # proporcionalmente según la frecuencia elegida.
        # ------------------------------------------------------------------
        else:
            if self.method == "fixed" and self.payment_frequency == "biweekly":
                delta = relativedelta(days=15)
            elif self.method == "fixed" and self.payment_frequency == "weekly":
                delta = relativedelta(weeks=1)
            else:
                delta = relativedelta(months=self.method_period)

            if not self.payment_on_first_period:
                date = initial_date + delta
                initial_date = date

            for i in range(1, self.periods + 1):
                line = self.env["account.loan.line"].create(
                    self._new_line_vals(i, date, amount)
                )
                line._check_amount()
                date = initial_date + delta * i
                amount -= line.payment_amount - line.interests_amount

        if self.long_term_loan_account_id:
            self._check_long_term_principal_amount()

    # ------------------------------------------------------------------
    # Actions / Views
    # ------------------------------------------------------------------

    def view_account_moves(self):
        self.ensure_one()
        result = self.env["ir.actions.act_window"]._for_xml_id(
            "account.action_move_line_form"
        )
        result["domain"] = [("loan_id", "=", self.id)]
        return result

    def view_account_invoices(self):
        self.ensure_one()
        result = self.env["ir.actions.act_window"]._for_xml_id(
            "account.action_move_out_invoice_type"
        )
        result["domain"] = [("loan_id", "=", self.id), ("move_type", "=", "out_invoice")]
        return result

    @api.model
    def _generate_loan_entries(self, date):
        res = []
        for record in self.search(
            [("state", "=", "posted"), ("is_leasing", "=", False)]
        ):
            lines = record.line_ids.filtered(
                lambda r: r.date <= date and not r.move_ids
            )
            res += lines._generate_move()
        return res

    @api.model
    def _generate_leasing_entries(self, date):
        res = []
        for record in self.search(
            [("state", "=", "posted"), ("is_leasing", "=", True)]
        ):
            res += record.line_ids.filtered(
                lambda r: r.date <= date and not r.move_ids
            )._generate_invoice()
        return res