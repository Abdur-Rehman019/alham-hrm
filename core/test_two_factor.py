import datetime
import re
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase, override_settings
from django_otp.oath import totp
from django_otp.plugins.otp_static.models import StaticDevice
from django_otp.plugins.otp_totp.models import TOTPDevice

from employees.models import Employee

PW = 'Str0ng!Pass#2026'


def current_code(device):
    return f'{totp(device.bin_key, step=device.step, t0=device.t0, digits=device.digits):06d}'


@override_settings(ADMIN_2FA_REQUIRED=True)
class TwoFactorTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('boss', 'boss@alham.pk', PW)

    def _set_up_two_factor(self):
        self.client.force_login(self.admin)
        self.client.get('/accounts/two-factor/setup/')
        device = TOTPDevice.objects.get(user=self.admin)
        response = self.client.post('/accounts/two-factor/setup/', {'code': current_code(device)})
        codes = re.findall(r'<code class="d-block border rounded py-2"[^>]*>([^<]+)</code>', response.content.decode())
        return device, codes

    def test_admin_without_two_factor_must_set_it_up_first(self):
        self.client.force_login(self.admin)
        for url in ['/', '/payroll/generate/', '/employees/', '/admin/']:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertTrue(response['Location'].startswith('/accounts/two-factor/setup/'), url)
        page = self.client.get('/accounts/two-factor/setup/')
        self.assertContains(page, '<svg')

    def test_setup_with_correct_code_turns_it_on_and_shows_backup_codes(self):
        device, codes = self._set_up_two_factor()
        device.refresh_from_db()
        self.assertTrue(device.confirmed)
        self.assertEqual(len(codes), 10)
        self.assertEqual(self.client.get('/').status_code, 200)

    def test_wrong_setup_code_is_rejected(self):
        self.client.force_login(self.admin)
        self.client.get('/accounts/two-factor/setup/')
        response = self.client.post('/accounts/two-factor/setup/', {'code': '000000'})
        self.assertContains(response, "didn&#x27;t match")
        self.assertFalse(TOTPDevice.objects.get(user=self.admin).confirmed)

    def test_every_new_sign_in_needs_a_code(self):
        device, _ = self._set_up_two_factor()
        self.client.logout()
        self.client.force_login(self.admin)
        response = self.client.get('/payroll/generate/')
        self.assertRedirects(response, '/accounts/two-factor/verify/?next=%2Fpayroll%2Fgenerate%2F',
                             fetch_redirect_response=False)
        self.assertContains(self.client.post('/accounts/two-factor/verify/', {'code': '123456'}), "didn&#x27;t work")
        TOTPDevice.objects.filter(pk=device.pk).update(throttling_failure_count=0, throttling_failure_timestamp=None,
                                                       last_t=-1)
        device.refresh_from_db()
        response = self.client.post('/accounts/two-factor/verify/',
                                    {'code': current_code(device), 'next': '/payroll/generate/'})
        self.assertRedirects(response, '/payroll/generate/', fetch_redirect_response=False)
        self.assertEqual(self.client.get('/payroll/generate/').status_code, 200)

    def test_backup_code_works_once(self):
        _, codes = self._set_up_two_factor()
        for attempt in range(2):
            self.client.logout()
            self.client.force_login(self.admin)
            response = self.client.post('/accounts/two-factor/verify/', {'code': codes[0]})
            if attempt == 0:
                self.assertRedirects(response, '/accounts/post-login/', fetch_redirect_response=False)
            else:
                self.assertEqual(response.status_code, 200)
        self.assertEqual(StaticDevice.objects.get(user=self.admin).token_set.count(), 9)

    def test_off_site_next_is_ignored(self):
        device, _ = self._set_up_two_factor()
        self.client.logout()
        self.client.force_login(self.admin)
        response = self.client.post('/accounts/two-factor/verify/',
                                    {'code': current_code(device), 'next': 'https://evil.example/'})
        self.assertNotIn('evil', response.get('Location', ''))

    def test_employees_are_not_asked_for_a_code(self):
        user = User.objects.create_user('ana', password=PW)
        employee = Employee.objects.create(name='Ana Khan', role='counselor', monthly_salary=30000,
                                           joined_on=datetime.date(2024, 1, 1))
        Employee.objects.filter(pk=employee.pk).update(user=user)
        self.client.force_login(user)
        self.assertEqual(self.client.get('/attendance/portal/').status_code, 200)

    def test_reset_command_forces_new_setup(self):
        self._set_up_two_factor()
        call_command('reset_two_factor', 'boss', stdout=StringIO())
        self.assertFalse(TOTPDevice.objects.filter(user=self.admin).exists())
        self.client.logout()
        self.client.force_login(self.admin)
        response = self.client.get('/')
        self.assertTrue(response['Location'].startswith('/accounts/two-factor/setup/'))
