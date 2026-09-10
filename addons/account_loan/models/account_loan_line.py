# Copyright 2018 Creu Blanca
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

import logging

from odoo import Command, _, api, fields, models
from odoo.exceptions import UserError
from odoo.tools import float_is_zero

_logger = logging.getLogger(__name__)
try:
    import numpy_financial
except (OSError, ImportError) as err:
    _logger.error(err)


class AccountLoanLine(models.Model):
    _name = "account.loan.line"
    _description = "Cuota de Préstamo"
    _order = "sequence asc"

    name = fields.Char(compute="_compute_name")
    loan_id = fields.Many2one(
        "account.loan",
        required=True,
        readonly=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        "res.company",
        related="loan_id.company_id",
        store=True,
    )
    partner_id = fields.Many2one("res.partner", related="loan_id.partner_id")
    is_leasing = fields.Boolean(related="loan_id.is_leasing")
    journal_id = fields.Many2one("account.journal", related="loan_id.journal_id")
    short_term_loan_account_id = fields.Many2one(
        "account.account",
        related="loan_id.short_term_loan_account_id",
    )
    interest_expenses_account_id = fields.Many2one(
        "account.account",
        related="loan_id.interest_expenses_account_id",
    )
    loan_type = fields.Selection(related="loan_id.loan_type")
    # Método del préstamo padre — usado para guardar comportamiento por tipo
    method = fields.Selection(related="loan_id.method", store=True)
    loan_state = fields.Selection(
        related="loan_id.state",
        readonly=True,
        store=True,
    )
    sequence = fields.Integer(required=True, readonly=True)
    date = fields.Date(
        required=True,
        readonly=True,
        string="Fecha de Pago",
        help="Fecha en que se registrará el pago",
    )
    long_term_loan_account_id = fields.Many2one(
        "account.account",
        related="loan_id.long_term_loan_account_id",
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="loan_id.currency_id",
    )
    rate = fields.Float(
        readonly=False,
        store=True,
        digits=(8, 6),
        compute="_compute_rate",
        string="Interés (%)",
        default=0.0,
    )
    pending_principal_amount = fields.Monetary(
        currency_field="currency_id",
        readonly=False,
        string="Capital Pendiente",
        help="Capital pendiente antes de este pago",
    )
    long_term_pending_principal_amount = fields.Monetary(
        currency_field="currency_id",
        readonly=True,
        help="Capital pendiente a más de 12 meses antes de este pago",
    )
    payment_amount = fields.Monetary(
        currency_field="currency_id",
        readonly=False,
        store=True,
        compute="_compute_payment_amount",
        string="Importe de Cuota",
        help="Importe total a pagar en esta cuota",
    )
    interests_amount = fields.Monetary(
        currency_field="currency_id",
        readonly=False,
        store=True,
        compute="_compute_interests_amount",
        string="Intereses",
        help="Parte de la cuota correspondiente a intereses",
    )
    principal_amount = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_principal_amount",
        store=True,
        readonly=False,  # Necesario para poder escribirlo directamente en stable_fixed
        string="Capital",
        help="Parte de la cuota que reduce el capital pendiente",
    )
    long_term_principal_amount = fields.Monetary(
        currency_field="currency_id",
        readonly=True,
        help="Reducción de capital a largo plazo en esta cuota",
    )
    final_pending_principal_amount = fields.Monetary(
        currency_field="currency_id",
        compute="_compute_amounts",
        store=True,
        string="Capital Pendiente Final",
        help="Capital pendiente después de este pago",
    )
    move_ids = fields.One2many(
        "account.move",
        inverse_name="loan_line_id",
    )
    has_moves = fields.Boolean(compute="_compute_has_moves")
    has_invoices = fields.Boolean(compute="_compute_has_invoices")

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------

    @api.depends("interests_amount", "pending_principal_amount")
    def _compute_rate(self):
        for record in self:
            rate = 0
            if not float_is_zero(record.pending_principal_amount, precision_digits=2):
                rate = (record.interests_amount * 100) / record.pending_principal_amount
            record.rate = rate

    @api.depends("rate")
    def _compute_interests_amount(self):
        for record in self:
            # Para stable_fixed los intereses se calculan y escriben directamente
            # al crear las líneas. No se recalculan aquí.
            if record.method == "stable_fixed":
                continue
            if record.interests_amount and record.pending_principal_amount:
                record.interests_amount = (
                    record.pending_principal_amount * record.rate
                ) / 100

    @api.depends("move_ids")
    def _compute_has_moves(self):
        for record in self:
            record.has_moves = bool(record.move_ids)

    @api.depends("move_ids")
    def _compute_has_invoices(self):
        for record in self:
            record.has_invoices = bool(record.move_ids)

    @api.depends("loan_id.name", "sequence")
    def _compute_name(self):
        for record in self:
            record.name = "%s-%d" % (record.loan_id.name, record.sequence)

    @api.depends("principal_amount", "interests_amount")
    def _compute_payment_amount(self):
        for rec in self:
            # stable_fixed: valores pre-calculados y escritos directamente, no recomputar
            if rec.method == "stable_fixed":
                continue
            rec.payment_amount = rec.principal_amount + rec.interests_amount

    @api.depends("payment_amount", "interests_amount", "pending_principal_amount")
    def _compute_amounts(self):
        for rec in self:
            rec.final_pending_principal_amount = (
                rec.pending_principal_amount - rec.payment_amount + rec.interests_amount
            )

    @api.depends("payment_amount", "interests_amount", "pending_principal_amount")
    def _compute_principal_amount(self):
        for rec in self:
            # stable_fixed: valores pre-calculados y escritos directamente, no recomputar
            if rec.method == "stable_fixed":
                continue
            rec.principal_amount = rec.payment_amount - rec.interests_amount

    # ------------------------------------------------------------------
    # Amount helpers (used by standard Odoo flow, not stable_fixed)
    # ------------------------------------------------------------------

    def _compute_amount(self):
        """Compute payment amount for standard Odoo loan types."""
        if self.sequence == self.loan_id.periods:
            return (
                self.pending_principal_amount
                + self.interests_amount
                - self.loan_id.residual_amount
            )
        if self.loan_type == "fixed-principal" and self.loan_id.round_on_end:
            return self.loan_id.fixed_amount + self.interests_amount
        if self.loan_type == "fixed-principal":
            return (self.pending_principal_amount - self.loan_id.residual_amount) / (
                self.loan_id.periods - self.sequence + 1
            ) + self.interests_amount
        if self.loan_type == "interest":
            return self.interests_amount
        if self.loan_type == "fixed-annuity" and self.loan_id.round_on_end:
            return self.loan_id.fixed_amount
        if self.loan_type == "fixed-annuity":
            return self.currency_id.round(
                -numpy_financial.pmt(
                    self.loan_id._loan_rate() / 100,
                    self.loan_id.periods - self.sequence + 1,
                    self.pending_principal_amount,
                    -self.loan_id.residual_amount,
                )
            )
        if self.loan_type == "fixed-annuity-begin" and self.loan_id.round_on_end:
            return self.loan_id.fixed_amount
        if self.loan_type == "fixed-annuity-begin":
            return self.currency_id.round(
                -numpy_financial.pmt(
                    self.loan_id._loan_rate() / 100,
                    self.loan_id.periods - self.sequence + 1,
                    self.pending_principal_amount,
                    -self.loan_id.residual_amount,
                    when="begin",
                )
            )

    def _check_amount(self):
        """Recompute amounts if the annuity has not been processed."""
        # stable_fixed: amounts are pre-calculated and fixed — skip
        if self.loan_id.method == "stable_fixed":
            return

        if self.move_ids:
            raise UserError(
                _("No se puede recalcular el importe si ya existen asientos contables.")
            )
        if (
            self.sequence == self.loan_id.periods
            and self.loan_id.round_on_end
            and self.loan_type in ["fixed-annuity", "fixed-annuity-begin"]
        ):
            self.interests_amount = self.currency_id.round(
                self.loan_id.fixed_amount
                - self.pending_principal_amount
                + self.loan_id.residual_amount
            )
            self.payment_amount = self.currency_id.round(self._compute_amount())
        elif not self.loan_id.round_on_end:
            self.interests_amount = self.currency_id.round(self._compute_interest())
            self.payment_amount = self.currency_id.round(self._compute_amount())
        else:
            self.interests_amount = self._compute_interest()
            self.payment_amount = self._compute_amount()

    def _compute_interest(self):
        if self.loan_type == "fixed-annuity-begin":
            return -numpy_financial.ipmt(
                self.loan_id._loan_rate() / 100,
                2,
                self.loan_id.periods - self.sequence + 1,
                self.pending_principal_amount,
                -self.loan_id.residual_amount,
                when="begin",
            )
        return self.pending_principal_amount * self.loan_id._loan_rate() / 100

    # ------------------------------------------------------------------
    # Move / invoice reading after posting
    # ------------------------------------------------------------------

    def _check_move_amount(self):
        """
        Actualiza los importes de la cuota leyendo el asiento contable ya publicado.
        Lógica: somos prestamistas, los intereses van en CRÉDITO (ingresos),
        la cuenta por cobrar se reduce en CRÉDITO.
        """
        self.ensure_one()
        interests_moves = self.move_ids.mapped("line_ids").filtered(
            lambda r: r.account_id == self.loan_id.interest_expenses_account_id
        )
        short_term_moves = self.move_ids.mapped("line_ids").filtered(
            lambda r: r.account_id == self.loan_id.short_term_loan_account_id
        )
        long_term_moves = self.move_ids.mapped("line_ids").filtered(
            lambda r: r.account_id == self.loan_id.long_term_loan_account_id
        )
        # Intereses en crédito (ingreso)
        self.interests_amount = sum(interests_moves.mapped("credit")) - sum(
            interests_moves.mapped("debit")
        )
        # Capital largo plazo en crédito
        self.long_term_principal_amount = sum(long_term_moves.mapped("credit")) - sum(
            long_term_moves.mapped("debit")
        )
        # Capital corto plazo en crédito (reduce activo)
        self.payment_amount = (
            sum(short_term_moves.mapped("credit"))
            - sum(short_term_moves.mapped("debit"))
            + self.long_term_principal_amount
            + self.interests_amount
        )

    # ------------------------------------------------------------------
    # Move/invoice generation
    # ------------------------------------------------------------------

    def _move_vals(self, journal=False, account=False):
        return {
            "loan_line_id": self.id,
            "loan_id": self.loan_id.id,
            "date": self.date,
            "ref": self.name,
            "journal_id": (journal and journal.id) or self.loan_id.journal_id.id,
            "line_ids": [
                Command.create(vals) for vals in self._move_line_vals(account=account)
            ],
        }

    def _move_line_vals(self, account=False):
        """
        Genera los apuntes contables del cobro de una cuota.

        Asiento del prestamista:
            Db  Cuentas por Cobrar (deudor)        ← cuota total
                Cr  Ingresos por Intereses          ← intereses
                Cr  Préstamos por Cobrar CP         ← capital
        """
        vals = []
        partner = self.loan_id.partner_id.with_company(self.loan_id.company_id)

        partner_account = (
            partner.property_account_receivable_id
            if self.payment_amount > 0
            else partner.property_account_payable_id
        )

        # Débito: lo que el cliente nos debe (cuota total)
        vals.append(
            {
                "account_id": (account and account.id) or partner_account.id,
                "partner_id": partner.id,
                "debit": self.payment_amount if self.payment_amount > 0 else 0,
                "credit": -self.payment_amount if self.payment_amount < 0 else 0,
            }
        )

        if self.interests_amount:
            amount = self.interests_amount
            # Crédito: ingresos por intereses
            vals.append(
                {
                    "account_id": self.loan_id.interest_expenses_account_id.id,
                    "credit": amount if amount > 0 else 0,
                    "debit": -amount if amount < 0 else 0,
                }
            )

        diff_amount = self.payment_amount - self.interests_amount  # = principal
        # Crédito: reduce la cuenta por cobrar (activo)
        vals.append(
            {
                "account_id": self.loan_id.short_term_loan_account_id.id,
                "credit": diff_amount if diff_amount > 0 else 0,
                "debit": -diff_amount if diff_amount < 0 else 0,
            }
        )

        if self.long_term_loan_account_id and self.long_term_principal_amount:
            amount = self.long_term_principal_amount
            vals.append(
                {
                    "account_id": self.loan_id.short_term_loan_account_id.id,
                    "debit": amount if amount > 0 else 0,
                    "credit": -amount if amount < 0 else 0,
                }
            )
            vals.append(
                {
                    "account_id": self.long_term_loan_account_id.id,
                    "credit": amount if amount > 0 else 0,
                    "debit": -amount if amount < 0 else 0,
                }
            )
        return vals

    def _invoice_vals(self):
        return {
            "loan_line_id": self.id,
            "loan_id": self.loan_id.id,
            "move_type": "out_invoice",
            "partner_id": self.loan_id.partner_id.id,
            "invoice_date": self.date,
            "journal_id": self.loan_id.journal_id.id,
            "company_id": self.loan_id.company_id.id,
            "invoice_line_ids": [
                Command.create(vals) for vals in self._invoice_line_vals()
            ],
        }

    def _invoice_line_vals(self):
        vals = list()
        vals.append(
            {
                "product_id": self.loan_id.product_id.id,
                "name": self.loan_id.product_id.name,
                "quantity": 1,
                "price_unit": self.principal_amount,
                "account_id": self.loan_id.short_term_loan_account_id.id,
            }
        )
        vals.append(
            {
                "product_id": self.loan_id.interests_product_id.id,
                "name": self.loan_id.interests_product_id.name,
                "quantity": 1,
                "price_unit": self.interests_amount,
                "account_id": self.loan_id.interest_expenses_account_id.id,
            }
        )
        return vals

    def _generate_move(self, journal=False, account=False):
        """Genera y publica el asiento contable de la cuota."""
        res = []
        for record in self:
            if not record.move_ids:
                if record.loan_id.line_ids.filtered(
                    lambda r, record=record: r.date < record.date and not r.move_ids
                ):
                    raise UserError(_("Deben procesarse primero las cuotas anteriores."))
                move = self.env["account.move"].create(
                    record._move_vals(journal=journal, account=account)
                )
                move.action_post()
                res.append(move.id)
        return res

    def _long_term_move_vals(self):
        return {
            "loan_line_id": self.id,
            "loan_id": self.loan_id.id,
            "date": self.date,
            "ref": self.name,
            "journal_id": self.loan_id.journal_id.id,
            "line_ids": [
                Command.create(vals) for vals in self._get_long_term_move_line_vals()
            ],
        }

    def _generate_invoice(self):
        res = []
        for record in self:
            if not record.move_ids:
                if record.loan_id.line_ids.filtered(
                    lambda r, record=record: r.date < record.date and not r.move_ids
                ):
                    raise UserError(_("Deben procesarse primero las cuotas anteriores."))
                invoice = self.env["account.move"].create(record._invoice_vals())
                res.append(invoice.id)
                for line in invoice.invoice_line_ids:
                    line.tax_ids = line._get_computed_taxes()
                invoice.flush_recordset()
                invoice.filtered(
                    lambda m: m.currency_id.round(m.amount_total) < 0
                ).action_switch_move_type()
                if record.loan_id.post_invoice:
                    invoice.action_post()
                if (
                    record.long_term_loan_account_id
                    and record.long_term_principal_amount != 0
                ):
                    move = self.env["account.move"].create(record._long_term_move_vals())
                    if record.loan_id.post_invoice:
                        move.action_post()
                    res.append(move.id)
        return res

    def _get_long_term_move_line_vals(self):
        return [
            {
                "account_id": self.loan_id.short_term_loan_account_id.id,
                "credit": self.long_term_principal_amount,
                "debit": 0,
            },
            {
                "account_id": self.long_term_loan_account_id.id,
                "credit": 0,
                "debit": self.long_term_principal_amount,
            },
        ]

    # ------------------------------------------------------------------
    # UI Actions
    # ------------------------------------------------------------------

    def view_account_values(self):
        self.ensure_one()
        if self.is_leasing:
            return self.view_account_invoices()
        return self.view_account_moves()

    def view_process_values(self):
        self.ensure_one()
        if self.is_leasing:
            self._generate_invoice()
        else:
            self._generate_move()
        return self.view_account_values()

    def view_account_moves(self):
        self.ensure_one()
        result = self.env["ir.actions.act_window"]._for_xml_id(
            "account.action_move_line_form"
        )
        result["context"] = {
            "default_loan_line_id": self.id,
            "default_loan_id": self.loan_id.id,
        }
        result["domain"] = [("loan_line_id", "=", self.id)]
        if len(self.move_ids) == 1:
            res = self.env.ref("account.view_move_form", False)
            result["views"] = [(res and res.id or False, "form")]
            result["res_id"] = self.move_ids.id
        return result

    def view_account_invoices(self):
        self.ensure_one()
        result = self.env["ir.actions.act_window"]._for_xml_id(
            "account.action_move_out_invoice_type"
        )
        result["context"] = {
            "default_loan_line_id": self.id,
            "default_loan_id": self.loan_id.id,
        }
        result["domain"] = [("loan_line_id", "=", self.id)]
        if len(self.move_ids) == 1:
            res = self.env.ref("account.view_move_form", False)
            result["views"] = [(res and res.id or False, "form")]
            result["res_id"] = self.move_ids.id
        return result