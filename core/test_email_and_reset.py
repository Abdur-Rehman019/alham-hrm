import datetime
import json
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.core.mail import EmailMessage
from django.test import TestCase, override_settings

from employees.models import Employee

PW = 'Str0ng!Pass#2026'
LOCMEM = 'django.core.mail.backends.locmem.EmailBackend'
CONSOLE = 'django.core.mail.backends.console.EmailBackend'


class PasswordResetTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('ana', password=PW)  # login created without an email
        self.employee = Employee.objects.create(
            name='Ana Khan', role='counselor', monthly_salary=30000,
            joined_on=datetime.date(2024, 1, 1), email='ana@alham.pk',
        )
        Employee.objects.filter(pk=self.employee.pk).update(user=self.user)

    @override_settings(EMAIL_BACKEND=LOCMEM)
    def test_reset_link_sent_to_hr_email_when_login_has_none(self):
        response = self.client.post('/accounts/password-reset/', {'email': 'ANA@alham.pk'})
        self.assertRedirects(response, '/accounts/password-reset/done/')
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['ANA@alham.pk'])
        self.assertIn('/accounts/reset/', mail.outbox[0].body)
        self.assertIn('Your username is: ana', mail.outbox[0].body)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'ANA@alham.pk')

    @override_settings(EMAIL_BACKEND=LOCMEM)
    def test_unknown_email_looks_the_same_but_sends_nothing(self):
        response = self.client.post('/accounts/password-reset/', {'email': 'nobody@alham.pk'})
        self.assertRedirects(response, '/accounts/password-reset/done/')
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(EMAIL_BACKEND=CONSOLE)
    def test_unconfigured_email_is_explained_instead_of_pretending(self):
        response = self.client.post('/accounts/password-reset/', {'email': 'ana@alham.pk'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ask HR to reset your password')

    @override_settings(EMAIL_BACKEND=LOCMEM)
    def test_send_failure_does_not_crash(self):
        with mock.patch('django.core.mail.EmailMultiAlternatives.send', side_effect=OSError('network down')):
            response = self.client.post('/accounts/password-reset/', {'email': 'ana@alham.pk'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'could not send the email')

    @override_settings(EMAIL_BACKEND=LOCMEM)
    def test_requests_are_rate_limited(self):
        for _ in range(5):
            self.client.post('/accounts/password-reset/', {'email': 'ana@alham.pk'})
        response = self.client.post('/accounts/password-reset/', {'email': 'ana@alham.pk'})
        self.assertContains(response, 'Too many reset requests')
        self.assertEqual(len(mail.outbox), 5)

    @override_settings(EMAIL_BACKEND=LOCMEM)
    def test_completing_reset_clears_forced_password_change(self):
        Employee.objects.filter(pk=self.employee.pk).update(must_change_password=True)
        self.client.post('/accounts/password-reset/', {'email': 'ana@alham.pk'})
        link = next(line for line in mail.outbox[0].body.splitlines() if '/accounts/reset/' in line)
        path = link.split('://', 1)[1].split('/', 1)[1]
        response = self.client.get('/' + path, follow=True)
        new = 'An0ther!Pass#2026'
        response = self.client.post(response.redirect_chain[-1][0], {'new_password1': new, 'new_password2': new})
        self.assertRedirects(response, '/accounts/reset/done/', fetch_redirect_response=False)
        self.employee.refresh_from_db()
        self.assertFalse(self.employee.must_change_password)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(new))
        done = self.client.get('/accounts/reset/done/')
        self.assertContains(done, 'The password for <strong>ana</strong> has been changed')

    @override_settings(EMAIL_BACKEND=LOCMEM)
    def test_shared_email_sends_one_clearly_labelled_link_per_account(self):
        User.objects.create_superuser('boss', 'ana@alham.pk', PW)
        self.client.post('/accounts/password-reset/', {'email': 'ana@alham.pk'})
        subjects = sorted(m.subject for m in mail.outbox)
        self.assertEqual(subjects, ['ALHAM HRM — Password reset for ana', 'ALHAM HRM — Password reset for boss'])


class DemoAddressTests(TestCase):
    """Demo employees start with @example.invalid addresses on both the HR record and the login."""

    def setUp(self):
        cache.clear()
        self.admin = User.objects.create_superuser('boss', 'boss@alham.pk', PW)
        self.user = User.objects.create_user('demo_sara', email='demo.sara@example.invalid', password=PW)
        self.employee = Employee.objects.create(
            name='Sara Yousaf', role='counselor', monthly_salary=30000,
            joined_on=datetime.date(2024, 1, 1), email='demo.sara@example.invalid',
        )
        Employee.objects.filter(pk=self.employee.pk).update(user=self.user)
        self.employee.refresh_from_db()

    @override_settings(EMAIL_BACKEND=LOCMEM)
    def test_payslip_to_placeholder_address_is_refused_with_reason(self):
        from django.utils import timezone
        from payroll.views import _calculate_and_save_payroll
        today = timezone.localdate()
        payroll, _ = _calculate_and_save_payroll(self.employee, today.year, today.month)
        self.client.force_login(self.admin)
        response = self.client.post(f'/payroll/payslip/{payroll.pk}/approve/', follow=True)
        self.assertEqual(len(mail.outbox), 0)
        self.assertContains(response, 'placeholder address that cannot receive email')
        self.assertFalse(payroll.email_attempts.get().success)

    @override_settings(EMAIL_BACKEND=LOCMEM)
    def test_new_hr_email_is_used_for_payslips_and_login(self):
        from django.utils import timezone
        from payroll.views import _calculate_and_save_payroll
        self.employee.email = 'sara@gmail.com'
        self.employee.save()
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'sara@gmail.com')

        today = timezone.localdate()
        payroll, _ = _calculate_and_save_payroll(self.employee, today.year, today.month)
        self.client.force_login(self.admin)
        self.client.post(f'/payroll/payslip/{payroll.pk}/approve/')
        self.assertEqual(mail.outbox[0].to, ['sara@gmail.com'])

    @override_settings(EMAIL_BACKEND=LOCMEM)
    def test_reset_by_hr_email_reaches_it_even_if_login_has_placeholder(self):
        Employee.objects.filter(pk=self.employee.pk).update(email='sara@gmail.com')
        self.client.post('/accounts/password-reset/', {'email': 'sara@gmail.com'})
        self.assertEqual(mail.outbox[0].to, ['sara@gmail.com'])
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, 'sara@gmail.com')

    @override_settings(EMAIL_BACKEND=LOCMEM)
    def test_reset_to_placeholder_address_sends_nothing(self):
        self.client.post('/accounts/password-reset/', {'email': 'demo.sara@example.invalid'})
        self.assertEqual(len(mail.outbox), 0)


class BrevoBackendTests(TestCase):
    @override_settings(EMAIL_BACKEND='core.email.BrevoEmailBackend', BREVO_API_KEY='test-key',
                       DEFAULT_FROM_EMAIL='ALHAM HRM <hr@alham.pk>')
    def test_sends_message_with_attachment_over_https(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"messageId": "1"}'
        with mock.patch('core.email.urllib.request.urlopen', return_value=response) as urlopen:
            message = EmailMessage('Payslip', 'Hello', to=['ana@alham.pk'])
            message.attach('slip.pdf', b'%PDF-1.4', 'application/pdf')
            self.assertEqual(message.send(), 1)
        request = urlopen.call_args[0][0]
        self.assertEqual(request.full_url, 'https://api.brevo.com/v3/smtp/email')
        self.assertEqual(request.get_header('Api-key'), 'test-key')
        payload = json.loads(request.data)
        self.assertEqual(payload['sender'], {'email': 'hr@alham.pk', 'name': 'ALHAM HRM'})
        self.assertEqual(payload['to'], [{'email': 'ana@alham.pk'}])
        self.assertEqual(payload['attachment'][0]['name'], 'slip.pdf')

    @override_settings(EMAIL_BACKEND='core.email.BrevoEmailBackend', BREVO_API_KEY='')
    def test_missing_key_is_reported(self):
        from core.email import email_problem
        self.assertIn('BREVO_API_KEY', email_problem())


class HealthAndErrorPageTests(TestCase):
    def test_health_check(self):
        response = self.client.get('/healthz/')
        self.assertEqual(response.json(), {'status': 'ok'})

    def test_friendly_404(self):
        response = self.client.get('/no-such-page/')
        self.assertEqual(response.status_code, 404)

    def test_admin_login_cannot_be_removed_from_employee_page(self):
        boss = User.objects.create_superuser('boss', 'b@x.com', PW)
        staff = User.objects.create_user('helper', password=PW, is_staff=True)
        employee = Employee.objects.create(name='Helper', role='admin_staff', monthly_salary=30000,
                                           joined_on=datetime.date(2024, 1, 1))
        Employee.objects.filter(pk=employee.pk).update(user=staff)
        self.client.force_login(boss)
        self.client.post(f'/employees/{employee.pk}/remove-login/')
        self.assertTrue(User.objects.filter(pk=staff.pk).exists())
