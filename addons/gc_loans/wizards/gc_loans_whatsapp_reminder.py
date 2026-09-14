import urllib.parse

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class GcLoansWhatsappReminder(models.TransientModel):
    _name = "gc.loans.whatsapp.reminder"
    _description = "Recordatorio de Pago por WhatsApp"

    loan_line_id = fields.Many2one(
        "account.loan.line",
        string="Cuota",
        required=True,
        readonly=True,
    )
    partner_id = fields.Many2one(
        related="loan_line_id.partner_id",
        string="Deudor",
        readonly=True,
    )
    phone = fields.Char(
        string="Celular (WhatsApp)",
        required=True,
        help="Se completa con el celular del deudor. Ajusta el formato si es "
        "necesario (código de país + número, solo dígitos).",
    )
    message = fields.Text(string="Mensaje", required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        line_id = self.env.context.get("default_loan_line_id")
        if line_id:
            line = self.env["account.loan.line"].browse(line_id)
            res["phone"] = self._format_phone(
                line.partner_id.mobile or line.partner_id.phone
            )
            res["message"] = line._build_whatsapp_reminder_message()
        return res

    @staticmethod
    def _format_phone(phone):
        """Deja solo dígitos y antepone '1' (código RD/NANP) a números
        locales de 10 dígitos sin código de país."""
        if not phone:
            return ""
        digits = "".join(ch for ch in phone if ch.isdigit())
        if len(digits) == 10:
            digits = "1" + digits
        return digits

    def action_send(self):
        self.ensure_one()
        if not self.phone:
            raise UserError(
                _("Este deudor no tiene un número de celular registrado.")
            )
        text = urllib.parse.quote(self.message)
        url = "https://wa.me/{phone}?text={text}".format(
            phone=self.phone, text=text
        )
        self.loan_line_id.loan_id.message_post(
            body=_(
                "Recordatorio de pago enviado por WhatsApp a %(partner)s "
                "(cuota %(cuota)s)."
            )
            % {
                "partner": self.partner_id.name,
                "cuota": self.loan_line_id.name,
            }
        )
        return {
            "type": "ir.actions.act_url",
            "url": url,
            "target": "new",
        }
