{
    "name": "G&C Préstamos - Core",
    "version": "1.0",
    "author": "Hector Contreras",
    "category": "Financial",
    "summary": "Personalizaciones generales para Préstamos Express G&C",
    "depends": ["account_loan"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron_data.xml",
        "wizards/gc_loans_whatsapp_reminder_views.xml",
        "views/account_loan_line_seguimiento_views.xml",
        "views/account_loan_line_whatsapp_views.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "gc_loans/static/src/js/whatsapp_reminder_field.js",
            "gc_loans/static/src/xml/whatsapp_reminder_field.xml",
        ],
    },
    "installable": True,
    "application": True,
}