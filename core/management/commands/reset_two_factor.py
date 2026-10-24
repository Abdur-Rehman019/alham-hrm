from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice


class Command(BaseCommand):
    help = ("Remove a user's authenticator app and backup codes, e.g. after a lost phone. "
            "They set up two-factor sign-in again at their next sign-in.")

    def add_arguments(self, parser):
        parser.add_argument('username')

    def handle(self, username, **options):
        user = get_user_model().objects.filter(username=username).first()
        if user is None:
            raise CommandError(f'No user named "{username}".')
        totp, _ = TOTPDevice.objects.filter(user=user).delete()
        static, _ = StaticDevice.objects.filter(user=user).delete()
        from core import audit
        audit.record(user, 'security', note='Two-factor sign-in reset from the server command line')
        self.stdout.write(self.style.SUCCESS(
            f'Two-factor sign-in reset for {username} ({totp} app, {static} backup-code device removed). '
            'They will scan a new QR code at their next sign-in.'
        ))
