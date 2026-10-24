"""
Clear all demo data before going live and create the first real admin account.

    python manage.py prepare_launch                 # preview only: shows what would be deleted
    python manage.py prepare_launch --confirm       # deletes, after typing DELETE ALL DATA

Keeps only the office check-in location (Wi-Fi IPs and GPS point). Take a database backup first.
"""
import getpass
import os
import shutil

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email
from django.db import transaction

CONFIRM_PHRASE = 'DELETE ALL DATA'

# Deleted in this order (children before parents). Label -> plain-English name for the summary.
TO_DELETE = [
    ('payroll.PayslipEmail', 'payslip email records'),
    ('payroll.Payroll', 'payroll records'),
    ('payroll.StudentEnrollment', 'student enrollments'),
    ('payroll.IncentiveRule', 'incentive rules'),
    ('attendance.LeaveRequest', 'leave requests'),
    ('attendance.Leave', 'leave records'),
    ('attendance.DailyAttendance', 'attendance days'),
    ('employees.Employee', 'employees'),
    ('core.TrustedDevice', 'remembered computers'),
    ('otp_totp.TOTPDevice', 'authenticator apps'),
    ('otp_static.StaticDevice', 'backup-code sets'),
    ('axes.AccessAttempt', 'failed sign-in records'),
    ('axes.AccessFailureLog', 'failed sign-in log entries'),
    ('axes.AccessLog', 'sign-in log entries'),
    ('sessions.Session', 'open sessions'),
    ('auth.User', 'login accounts (admins included)'),
    ('core.AuditLog', 'audit log entries'),  # last: the deletions above write entries of their own
]


class Command(BaseCommand):
    help = 'Delete all demo data (keeping the office check-in location) and create the first real admin.'

    def add_arguments(self, parser):
        parser.add_argument('--confirm', action='store_true', help='Actually delete. Without it, only a preview is shown.')
        parser.add_argument('--admin-username')
        parser.add_argument('--admin-email')

    def _model(self, label):
        return get_user_model() if label == 'auth.User' else apps.get_model(label)

    def handle(self, *args, confirm=False, admin_username=None, admin_email=None, **options):
        self.stdout.write(self.style.WARNING('Data that will be permanently deleted:'))
        for label, name in TO_DELETE:
            self.stdout.write(f'  {self._model(label).objects.count():>6}  {name}')
        photos = os.path.join(settings.MEDIA_ROOT, 'employee_photos')
        self.stdout.write(f'  {"(all)":>6}  employee photos in {photos}')
        office = apps.get_model('attendance.OfficeLocation').objects.count()
        self.stdout.write(self.style.SUCCESS(f'Kept: office check-in location ({office} saved).'))

        if not confirm:
            self.stdout.write('\nPreview only; nothing was changed. Take a database backup, then run again with --confirm.')
            return

        self.stdout.write('')
        if input(f'This cannot be undone. Type {CONFIRM_PHRASE} to continue: ').strip() != CONFIRM_PHRASE:
            raise CommandError('Cancelled; nothing was changed.')

        username = (admin_username or input('New admin username: ')).strip()
        email = (admin_email or input('New admin email (company address): ')).strip()
        if not username:
            raise CommandError('A username is required; nothing was changed.')
        try:
            validate_email(email)
        except ValidationError:
            raise CommandError(f'"{email}" is not a valid email address; nothing was changed.')
        password = os.environ.get('LAUNCH_ADMIN_PASSWORD') or getpass.getpass('New admin password: ')
        if not os.environ.get('LAUNCH_ADMIN_PASSWORD') and getpass.getpass('Password again: ') != password:
            raise CommandError('Passwords do not match; nothing was changed.')
        User = get_user_model()
        try:
            password_validation.validate_password(password, User(username=username, email=email))
        except ValidationError as exc:
            raise CommandError('Password not accepted: ' + ' '.join(exc.messages) + ' Nothing was changed.')

        with transaction.atomic():
            for label, _ in TO_DELETE:
                self._model(label).objects.all().delete()
            admin = User.objects.create_superuser(username=username, email=email, password=password)
            apps.get_model('core.AuditLog').objects.all().delete()  # start the new log clean
            from core import audit
            audit.record(admin, 'security', note='All demo data cleared for launch; first admin account created')

        shutil.rmtree(photos, ignore_errors=True)
        shutil.rmtree(os.path.join(settings.MEDIA_ROOT, 'import_temp'), ignore_errors=True)
        self.stdout.write(self.style.SUCCESS(
            f'Done. Sign in as "{username}" (or {email}); you will set up two-factor sign-in first.'))
