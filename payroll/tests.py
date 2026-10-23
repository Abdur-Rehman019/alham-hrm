from django.test import TestCase
import datetime
import calendar
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import override_settings
from django.utils import timezone

from attendance.models import DailyAttendance, Leave
from employees.models import Employee
from payroll.calculations import _money, compute_payroll
from payroll.models import IncentiveRule, Payroll, PayslipEmail, StudentEnrollment
from payroll.views import _calculate_and_save_payroll


class PayrollWorkflowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('payroll-admin', 'admin@alham.pk', 'StrongPass!123')
        self.employee = Employee.objects.create(
            name='Salary Employee', role='counselor', monthly_salary='30000',
            joined_on=timezone.localdate(), email='personal@alham.pk',
        )
        self.client.force_login(self.admin)

    def test_compute_payroll_uses_whole_rupees_and_generating_page_agrees(self):
        today = timezone.localdate()
        result = compute_payroll(self.employee, today.year, today.month)
        self.assertIsInstance(result.net_pay, Decimal)
        self.assertEqual(result.net_pay.as_tuple().exponent, 0)
        response = self.client.post('/payroll/generate/', {
            'employee_id': self.employee.pk, 'month': today.month, 'year': today.year,
        })
        self.assertEqual(response.status_code, 302)
        saved = Payroll.objects.get(employee=self.employee, month=today.month, year=today.year)
        self.assertEqual(
            (saved.base_salary, saved.leave_deduction, saved.incentive_total, saved.net_pay),
            (result.base_salary, result.leave_deduction, result.incentive_total, result.net_pay),
        )
        page = self.client.get(
            f'/payroll/generate/?month={today.month}&year={today.year}'
        )
        self.assertContains(page, 'PKR 30000')
        self.assertNotContains(page, '30,000.00')

    def test_money_rounding_is_half_up_to_whole_rupees(self):
        self.assertEqual(_money(Decimal('1.5')), Decimal('2'))
        self.assertEqual(_money(Decimal('1.4')), Decimal('1'))
        self.assertEqual(_money(Decimal('-1.5')), Decimal('-2'))

    def test_employee_salary_rejects_decimal_rupees(self):
        employee = Employee(
            name='Decimal Salary', role='counselor', monthly_salary='30000.50',
            joined_on=timezone.localdate(),
        )
        with self.assertRaises(ValidationError):
            employee.full_clean()

    def test_absence_reduces_payroll_using_calendar_day_rate(self):
        today = timezone.localdate()
        first = datetime.date(today.year, today.month, 1)
        if first.weekday() == 6:
            first += datetime.timedelta(days=1)
        DailyAttendance.objects.create(employee=self.employee, date=first, status='absent')
        with mock.patch('django.utils.timezone.localdate', return_value=first + datetime.timedelta(days=1)):
            result = compute_payroll(self.employee, first.year, first.month)
        expected = (Decimal('30000') / Decimal(calendar.monthrange(first.year, first.month)[1])).quantize(Decimal('1'))
        self.assertEqual(result.leave_deduction, expected)

    def test_incentive_rule_backfills_only_zero_unpaid_enrollments_case_insensitively(self):
        today = timezone.localdate()
        missing = StudentEnrollment.objects.create(
            student_name='Missing rule', destination_country='tUrKeY',
            counselor=self.employee, confirmed_on=today,
        )
        paid = StudentEnrollment.objects.create(
            student_name='Paid zero', destination_country='TURKEY',
            counselor=self.employee, confirmed_on=today, incentive_paid=True,
        )
        fixed = StudentEnrollment.objects.create(
            student_name='Existing amount', destination_country='Turkey',
            counselor=self.employee, confirmed_on=today, incentive_amount=Decimal('500'),
        )
        IncentiveRule.objects.create(destination_country='Turkey', amount='1250.50')
        missing.refresh_from_db()
        paid.refresh_from_db()
        fixed.refresh_from_db()
        self.assertEqual(missing.incentive_amount, Decimal('1251'))
        self.assertEqual(paid.incentive_amount, Decimal('0'))
        self.assertEqual(fixed.incentive_amount, Decimal('500'))

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_email_attachment_and_hr_email_preference(self):
        # The HR record's email wins: it is the one admins edit. (alham.pk is reserved, so use real-looking domains.)
        self.employee.email = 'personal@alham.pk'
        self.employee.user = User.objects.create_user('staff-login', email='login@alham.pk', password='StrongPass!123')
        self.employee.save()
        today = timezone.localdate()
        payroll, _ = _calculate_and_save_payroll(self.employee, today.year, today.month)
        response = self.client.post(f'/payroll/payslip/{payroll.pk}/approve/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['personal@alham.pk'])
        self.assertIn(f"Your payslip for {calendar.month_name[today.month]} {today.year}", message.subject)
        self.assertTrue(message.attachments[0][0].endswith('.pdf'))
        self.assertTrue(message.attachments[0][2] == 'application/pdf')
        self.assertTrue(message.attachments[0][1].startswith(b'%PDF'))
        self.assertIn('Net pay: PKR 30,000', message.body)
        self.assertNotIn('.00', message.body)
        attempt = payroll.email_attempts.get()
        self.assertTrue(attempt.success)
        self.assertEqual(attempt.recipient, 'personal@alham.pk')
        payroll.refresh_from_db()
        self.assertTrue(payroll.is_approved)
        self.assertEqual(payroll.approved_by, self.admin)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.console.EmailBackend')
    def test_console_email_backend_is_not_reported_as_delivered(self):
        today = timezone.localdate()
        payroll, _ = _calculate_and_save_payroll(self.employee, today.year, today.month)

        with mock.patch('payroll.views.EmailMessage.send') as send:
            response = self.client.post(f'/payroll/payslip/{payroll.pk}/approve/')

        self.assertEqual(response.status_code, 302)
        send.assert_not_called()
        attempt = payroll.email_attempts.get()
        self.assertFalse(attempt.success)
        self.assertIn('only prints messages', attempt.error)
        self.assertIn('not configured', attempt.error)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_missing_email_and_outdated_payroll_are_logged_and_not_sent(self):
        self.employee.email = ''
        self.employee.save()
        today = timezone.localdate()
        payroll, _ = _calculate_and_save_payroll(self.employee, today.year, today.month)
        response = self.client.post(f'/payroll/payslip/{payroll.pk}/approve/')
        self.assertEqual(response.status_code, 302)
        attempt = payroll.email_attempts.get()
        self.assertFalse(attempt.success)
        self.assertIn('No email', attempt.error)
        payroll.refresh_from_db()
        self.assertTrue(payroll.is_approved)
        self.employee.email = 'personal@alham.pk'
        self.employee.save()
        response = self.client.post(f'/payroll/payslip/{payroll.pk}/email/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(payroll.email_attempts.order_by('-sent_at').first().success)
        payroll.base_salary = Decimal('31000.00')
        payroll.save()
        response = self.client.post(f'/payroll/payslip/{payroll.pk}/email/')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(payroll.email_attempts.count(), 3)
        self.assertIn('outdated', payroll.email_attempts.order_by('-sent_at').first().error.lower())
        self.assertEqual(len(mail.outbox), 1)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_approval_sends_once_and_resend_is_explicit(self):
        today = timezone.localdate()
        first, _ = _calculate_and_save_payroll(self.employee, today.year, today.month)
        self.client.post(f'/payroll/payslip/{first.pk}/approve/')
        self.client.post(f'/payroll/payslip/{first.pk}/approve/')
        self.assertEqual(first.email_attempts.count(), 1)
        self.client.post(f'/payroll/payslip/{first.pk}/email/')
        self.assertEqual(len(mail.outbox), 2)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_approval_delivery_failure_is_audited_and_can_be_retried(self):
        today = timezone.localdate()
        payroll, _ = _calculate_and_save_payroll(self.employee, today.year, today.month)
        with mock.patch('payroll.views.EmailMessage.send', side_effect=RuntimeError('smtp issue')):
            response = self.client.post(f'/payroll/payslip/{payroll.pk}/approve/')
        self.assertEqual(response.status_code, 302)
        payroll.refresh_from_db()
        self.assertTrue(payroll.is_approved)
        self.assertFalse(payroll.email_attempts.first().success)
        self.assertIn('smtp issue', payroll.email_attempts.first().error)
        response = self.client.post(f'/payroll/payslip/{payroll.pk}/email/')
        self.assertEqual(response.status_code, 302)
        self.assertTrue(payroll.email_attempts.order_by('-sent_at').first().success)
        self.assertEqual(len(mail.outbox), 1)

    def test_regenerating_changed_payroll_clears_approval(self):
        today = timezone.localdate()
        payroll, _ = _calculate_and_save_payroll(self.employee, today.year, today.month)
        payroll.is_approved = True
        payroll.approved_at = timezone.now()
        payroll.approved_by = self.admin
        payroll.save()
        self.employee.monthly_salary = Decimal('32000')
        self.employee.save()
        payroll, created = _calculate_and_save_payroll(self.employee, today.year, today.month)
        self.assertFalse(created)
        self.assertFalse(payroll.is_approved)
        self.assertIsNone(payroll.approved_at)
        self.assertIsNone(payroll.approved_by)

    def test_unapproved_payroll_cannot_be_emailed_even_by_admin(self):
        today = timezone.localdate()
        payroll, _ = _calculate_and_save_payroll(self.employee, today.year, today.month)
        response = self.client.post(f'/payroll/payslip/{payroll.pk}/email/')
        self.assertEqual(response.status_code, 302)
        attempt = payroll.email_attempts.get()
        self.assertFalse(attempt.success)
        self.assertIn('approved', attempt.error)
        self.assertEqual(mail.outbox, [])

    def test_employee_cannot_send_payslip_and_email_is_post_only(self):
        today = timezone.localdate()
        payroll, _ = _calculate_and_save_payroll(self.employee, today.year, today.month)
        self.assertEqual(self.client.get(f'/payroll/payslip/{payroll.pk}/email/').status_code, 405)
        employee_user = User.objects.create_user('blocked', password='StrongPass!123')
        self.employee.user = employee_user
        self.employee.save()
        client = self.client_class()
        client.force_login(employee_user)
        self.assertEqual(client.post(f'/payroll/payslip/{payroll.pk}/approve/').status_code, 302)
        self.assertEqual(client.post(f'/payroll/payslip/{payroll.pk}/email/').status_code, 302)
        self.assertFalse(payroll.email_attempts.exists())

# Create your tests here.
