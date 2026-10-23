from io import StringIO
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from attendance.models import DailyAttendance, Leave
from employees.models import Employee
from payroll.calculations import compute_payroll
from payroll.models import Payroll, StudentEnrollment


class SeedDemoDataTests(TestCase):
    def setUp(self):
        self.existing_employee = Employee.objects.create(
            name='Existing Staff',
            role='counselor',
            monthly_salary=35000,
            joined_on=timezone.localdate() - timedelta(days=365),
        )

    @override_settings(DEBUG=True)
    def test_seeds_only_demo_employees_and_is_idempotent(self):
        call_command('seed_demo_data', months=1, create_logins=True, stdout=StringIO())

        demo_employees = Employee.objects.filter(name__startswith='Demo -')
        self.assertEqual(demo_employees.count(), 6)
        self.assertEqual(User.objects.filter(username__startswith='demo_').count(), 6)
        self.assertGreater(DailyAttendance.objects.filter(employee__in=demo_employees).count(), 0)
        self.assertGreater(Leave.objects.filter(employee__in=demo_employees).count(), 0)
        self.assertGreater(StudentEnrollment.objects.filter(counselor__in=demo_employees).count(), 0)
        self.assertEqual(Payroll.objects.filter(employee__in=demo_employees).count(), 6)
        self.assertFalse(DailyAttendance.objects.filter(employee=self.existing_employee).exists())
        self.assertFalse(Payroll.objects.filter(employee=self.existing_employee).exists())

        for payroll in Payroll.objects.filter(employee__in=demo_employees):
            calculation = compute_payroll(payroll.employee, payroll.year, payroll.month)
            self.assertEqual(payroll.base_salary, calculation.base_salary)
            self.assertEqual(payroll.leave_deduction, calculation.leave_deduction)
            self.assertEqual(payroll.incentive_total, calculation.incentive_total)
            self.assertFalse(payroll.is_approved)

        counts_before = (
            DailyAttendance.objects.filter(employee__in=demo_employees).count(),
            Leave.objects.filter(employee__in=demo_employees).count(),
            StudentEnrollment.objects.filter(counselor__in=demo_employees).count(),
            Payroll.objects.filter(employee__in=demo_employees).count(),
        )
        call_command('seed_demo_data', months=1, create_logins=True, stdout=StringIO())
        counts_after = (
            DailyAttendance.objects.filter(employee__in=demo_employees).count(),
            Leave.objects.filter(employee__in=demo_employees).count(),
            StudentEnrollment.objects.filter(counselor__in=demo_employees).count(),
            Payroll.objects.filter(employee__in=demo_employees).count(),
        )
        self.assertEqual(counts_after, counts_before)

        for employee in demo_employees:
            employee.refresh_from_db()
            self.assertTrue(employee.must_change_password)
            self.assertTrue(employee.user.has_usable_password())

    @override_settings(DEBUG=False)
    def test_refuses_to_seed_without_debug_mode(self):
        with self.assertRaises(CommandError):
            call_command('seed_demo_data', months=1, stdout=StringIO())
        self.assertFalse(Employee.objects.filter(name__startswith='Demo -').exists())
