from django.apps import AppConfig


class PayrollConfig(AppConfig):
    name = 'payroll'

    def ready(self):
        from . import signals  # noqa: F401
