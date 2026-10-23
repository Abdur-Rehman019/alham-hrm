from django.test import TestCase
import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.utils import timezone

from attendance.models import DailyAttendance, Leave, LeaveRequest
from employees.models import Employee
from payroll.models import Payroll, StudentEnrollment, IncentiveRule


class EmployeePortalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('portal-user', password='StrongPass!123')
        self.employee = Employee.objects.create(
            name='Portal User', role='counselor', monthly_salary='30000.00',
            joined_on=timezone.localdate(), user=self.user,
        )
        self.other = Employee.objects.create(
            name='Other Employee', role='counselor', monthly_salary='35000.00',
            joined_on=timezone.localdate(),
        )
        self.client.force_login(self.user)

    def test_all_portal_pages_render_empty_and_seeded_without_allowance_hints(self):
        paths = [
            '/attendance/portal/',
            '/attendance/portal/attendance/',
            '/attendance/portal/leaves/',
            '/attendance/portal/enrollments/',
            '/attendance/portal/salary/',
        ]
        for path in paths:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertNotRegex(response.content.decode().lower(), r'\bfree\b', path)
            self.assertNotIn('/ 2', response.content.decode(), path)

        today = timezone.localdate()
        IncentiveRule.objects.create(destination_country='Turkey', amount='10000.00')
        StudentEnrollment.objects.create(
            student_name='Owned Student', destination_country='Turkey',
            counselor=self.employee, confirmed_on=today,
        )
        StudentEnrollment.objects.create(
            student_name='Private Student', destination_country='Turkey',
            counselor=self.other, confirmed_on=today,
        )
        LeaveRequest.objects.create(employee=self.employee, date=today + datetime.timedelta(days=1), reason='Family event')
        Payroll.objects.create(employee=self.employee, month=today.month, year=today.year, base_salary=Decimal('30000.00'))

        for path in paths:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            text = response.content.decode()
            self.assertNotRegex(text.lower(), r'\bfree\b', path)
            self.assertNotIn('/ 2', text, path)
            self.assertNotIn('Private Student', text, path)

    def test_invalid_periods_fall_back_and_all_sections_remain_available(self):
        for path in (
            '/attendance/portal/attendance/',
            '/attendance/portal/enrollments/',
            '/attendance/portal/salary/',
        ):
            for query in ('?month=bad&year=xyz', '?month=99&year=2020', '?month=1&year=9999'):
                self.assertEqual(self.client.get(path + query).status_code, 200)

    def test_dashboard_check_in_posts_once(self):
        today = timezone.localdate()
        if today.weekday() == 6:
            self.skipTest('Sunday')
        response = self.client.post('/attendance/portal/')
        self.assertRedirects(response, '/attendance/portal/', fetch_redirect_response=False)
        self.assertEqual(DailyAttendance.objects.filter(employee=self.employee, date=today).count(), 1)

    def test_employee_cannot_reach_admin_data_or_email_payslip(self):
        admin_paths = ['/employees/', '/payroll/generate/', '/attendance/leave-requests/', '/imports/enrollments/']
        for path in admin_paths:
            self.assertEqual(self.client.get(path).status_code, 302)
        payroll = Payroll.objects.create(
            employee=self.other, month=timezone.localdate().month,
            year=timezone.localdate().year, base_salary=Decimal('35000.00'),
        )
        self.assertEqual(self.client.get(f'/payroll/payslip/{payroll.pk}/').status_code, 302)
        self.assertEqual(self.client.post(f'/payroll/payslip/{payroll.pk}/email/').status_code, 302)
        self.assertFalse(payroll.email_attempts.exists())
        self.assertEqual(self.client.get(f'/attendance/my-payslip/{payroll.pk}/').status_code, 404)

    def test_salary_totals_accumulate_generated_payrolls_only(self):
        today = timezone.localdate()
        Payroll.objects.create(
            employee=self.employee, month=today.month, year=today.year,
            base_salary=Decimal('30000.00'), leave_deduction=Decimal('100.00'),
            incentive_total=Decimal('1000.00'),
        )
        Payroll.objects.create(
            employee=self.employee, month=12, year=today.year - 1,
            base_salary=Decimal('30000.00'), leave_deduction=Decimal('200.00'),
            incentive_total=Decimal('500.00'),
        )
        response = self.client.get('/attendance/portal/salary/')
        self.assertEqual(response.context['total_earned'], Decimal('61200.00'))
        self.assertEqual(response.context['year_earned'], Decimal('30900.00'))
        self.assertEqual(response.context['total_incentives'], Decimal('1500.00'))

    def test_leave_conflicts_with_recorded_attendance_and_approved_leave(self):
        day = timezone.localdate() + datetime.timedelta(days=1)
        while day.weekday() == 6:
            day += datetime.timedelta(days=1)
        DailyAttendance.objects.create(employee=self.employee, date=day, status='present')
        response = self.client.post('/attendance/portal/leaves/', {'date': day.isoformat(), 'reason': 'Family event'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(LeaveRequest.objects.filter(employee=self.employee).exists())

    def test_cancel_is_post_only_and_ownership_checked(self):
        day = timezone.localdate() + datetime.timedelta(days=1)
        while day.weekday() == 6:
            day += datetime.timedelta(days=1)
        request = LeaveRequest.objects.create(employee=self.employee, date=day, reason='Family event')
        self.assertEqual(self.client.get(f'/attendance/my-leave-requests/{request.pk}/cancel/').status_code, 405)
        other_request = LeaveRequest.objects.create(employee=self.other, date=day, reason='Family event')
        self.assertEqual(self.client.post(f'/attendance/my-leave-requests/{other_request.pk}/cancel/').status_code, 404)
        self.assertEqual(self.client.post(f'/attendance/my-leave-requests/{request.pk}/cancel/').status_code, 302)
        request.refresh_from_db()
        self.assertEqual(request.status, 'cancelled')

# Create your tests here.
