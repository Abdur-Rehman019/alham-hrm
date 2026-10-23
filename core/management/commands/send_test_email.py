from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError

from core.email import email_problem


class Command(BaseCommand):
    help = 'Send a test email to check that email delivery is set up, e.g. `python manage.py send_test_email you@example.com`.'

    def add_arguments(self, parser):
        parser.add_argument('recipient')

    def handle(self, recipient, **options):
        self.stdout.write(f'Email backend: {settings.EMAIL_BACKEND}')
        self.stdout.write(f'From address:  {settings.DEFAULT_FROM_EMAIL}')
        problem = email_problem()
        if problem:
            raise CommandError(problem)
        try:
            send_mail(
                'ALHAM HRM test email',
                'If you can read this, ALHAM HRM can send password reset links and payslips.',
                settings.DEFAULT_FROM_EMAIL,
                [recipient],
                fail_silently=False,
            )
        except Exception as exc:
            raise CommandError(f'Sending failed: {exc}') from exc
        self.stdout.write(self.style.SUCCESS(f'Sent to {recipient}. Check the inbox and the spam folder.'))
