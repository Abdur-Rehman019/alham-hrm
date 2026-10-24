import datetime
from decimal import Decimal
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from django.test import TestCase

from attendance.models import DailyAttendance, OfficeLocation
from core.models import AuditLog
from employees.models import Employee
from payroll.models import IncentiveRule, StudentEnrollment

PW = 'Str0ng!Pass#2026'
NEW_PW = 'Launch!Day#2026x'


class EmailOrUsernameSignInTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ali', email='ali@alham.pk', password=PW)

    def test_username_or_email_any_case(self):
        for name in ['ali', 'ALI', 'ali@alham.pk', ' Ali@Alham.PK ']:
            response = self.client.post('/accounts/login/', {'username': name, 'password': PW})
            self.assertEqual(response.status_code, 302, name)
            self.client.logout()

    def test_hr_record_email_also_works(self):
        employee = Employee.objects.create(name='Ali Raza', role='counselor', monthly_salary=30000,
                                           joined_on=datetime.date(2024, 1, 1), email='ali.raza@alham.pk')
        Employee.objects.filter(pk=employee.pk).update(user=self.user)
        response = self.client.post('/accounts/login/', {'username': 'ali.raza@alham.pk', 'password': PW})
        self.assertEqual(response.status_code, 302)

    def test_wrong_password_and_shared_email_fail(self):
        response = self.client.post('/accounts/login/', {'username': 'ali@alham.pk', 'password': 'nope'})
        self.assertContains(response, 'Wrong email/username or password')
        User.objects.create_user('ali2', email='ali@alham.pk', password=PW)
        response = self.client.post('/accounts/login/', {'username': 'ali@alham.pk', 'password': PW})
        self.assertEqual(response.status_code, 200)


class CreateLoginEmailTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser('boss', 'boss@alham.pk', PW))
        self.employee = Employee.objects.create(name='Sara Yousaf', role='counselor', monthly_salary=30000,
                                                joined_on=datetime.date(2024, 1, 1), email='sara@alham.pk')

    def test_username_suggested_from_company_email(self):
        page = self.client.get(f'/employees/{self.employee.pk}/create-login/')
        self.assertContains(page, 'value="sara"')

    def test_email_already_used_by_another_login_is_refused(self):
        User.objects.create_user('someone', email='sara@alham.pk', password=PW)
        response = self.client.post(f'/employees/{self.employee.pk}/create-login/', {
            'username': 'sara', 'email': '', 'password1': PW, 'password2': PW})
        self.assertContains(response, 'Another account already uses this email')


class PrepareLaunchTests(TestCase):
    def setUp(self):
        User.objects.create_superuser('demo-admin', 'demo@alham.pk', PW)
        employee = Employee.objects.create(name='Demo - Ana', role='counselor', monthly_salary=30000,
                                           joined_on=datetime.date(2024, 1, 1))
        IncentiveRule.objects.create(destination_country='UK', amount=Decimal('5000'))
        StudentEnrollment.objects.create(student_name='S', destination_country='UK', counselor=employee,
                                         confirmed_on=datetime.date(2026, 10, 1))
        DailyAttendance.objects.create(employee=employee, date=datetime.date(2026, 10, 1), status='present')
        OfficeLocation.objects.create(latitude=Decimal('31.5'), longitude=Decimal('74.3'), allowed_ips='203.0.113.10')

    def _run(self, answers, **options):
        out = StringIO()
        with mock.patch('builtins.input', side_effect=answers), \
                mock.patch('getpass.getpass', side_effect=[NEW_PW, NEW_PW]):
            call_command('prepare_launch', stdout=out, **options)
        return out.getvalue()

    def test_preview_changes_nothing(self):
        out = self._run([])
        self.assertIn('Preview only', out)
        self.assertEqual(Employee.objects.count(), 1)
        self.assertEqual(User.objects.count(), 1)

    def test_wrong_phrase_cancels(self):
        with self.assertRaises(CommandError):
            self._run(['delete'], confirm=True)
        self.assertEqual(Employee.objects.count(), 1)

    def test_weak_password_cancels_before_deleting(self):
        with mock.patch('builtins.input', side_effect=['DELETE ALL DATA', 'hr', 'hr@alham.pk']), \
                mock.patch('getpass.getpass', side_effect=['12345678', '12345678']), \
                self.assertRaises(CommandError):
            call_command('prepare_launch', confirm=True, stdout=StringIO())
        self.assertEqual(Employee.objects.count(), 1)

    def test_full_reset_keeps_office_location_and_creates_new_admin(self):
        out = self._run(['DELETE ALL DATA', 'hr.admin', 'hr@alham.pk'], confirm=True)
        self.assertIn('Done', out)
        for model in (Employee, StudentEnrollment, IncentiveRule, DailyAttendance):
            self.assertFalse(model.objects.exists(), model)
        self.assertEqual(list(User.objects.values_list('username', flat=True)), ['hr.admin'])
        admin = User.objects.get()
        self.assertTrue(admin.is_superuser and admin.check_password(NEW_PW))
        self.assertEqual(OfficeLocation.objects.get().allowed_ips, '203.0.113.10')
        self.assertEqual(AuditLog.objects.get().note,
                         'All demo data cleared for launch; first admin account created')
