from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Warning, register


class CoreConfig(AppConfig):
    name = 'core'

    def ready(self):
        register(check_email_delivery)


def check_email_delivery(app_configs, **kwargs):
    """Shows in the deploy log when production cannot send password resets or payslips."""
    from .email import email_problem
    problem = None if settings.DEBUG else email_problem()
    if not problem:
        return []
    return [Warning(
        f'ALHAM HRM cannot send email: {problem}.',
        hint='Set BREVO_API_KEY and DEFAULT_FROM_EMAIL in the Railway service variables (see README).',
        id='core.W001',
    )]
