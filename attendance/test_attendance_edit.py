import datetime
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from attendance.models import DailyAttendance, Leave
from core.models import AuditLog
from employees.models import Employee
from payroll.models import Payroll

PW = 'Str0ng!Pass#2026'
TODAY = datetime.date(2026, 10, 24)


class MidnightCheckInTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ana', password=PW)
        self.employee = Employee.objects.create(name='Ana Khan', role='counselor', monthly_salary=30000,
                                                joined_on=datetime.date(2024, 1, 1))
        Employee.objects.filter(pk=self.employee.pk).update(user=self.user)
        self.client.force_login(self.user)

    def _check_in_at(self, hour, minute):
        moment = timezone.make_aware(datetime.datetime(2026, 10, 21, hour, minute))
        with mock.patch('attendance.employee_portal.timezone.localtime', return_value=moment), \
                mock.patch('attendance.employee_portal.timezone.localdate', return_value=moment.date()):
            return self.client.post('/attendance/portal/', follow=True)

    def test_midnight_and_early_morning_check_ins_are_refused(self):
        for hour, minute in [(0, 5), (3, 30), (7, 59)]:
            response = self._check_in_at(hour, minute)
            self.assertContains(response, 'Check-in opens at 8:00 AM')
        self.assertFalse(DailyAttendance.objects.exists())

    def test_check_in_from_8_am_is_accepted(self):
        self._check_in_at(8, 0)
        self.assertEqual(DailyAttendance.objects.get().status, 'present')


class AttendanceEditTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('boss', 'boss@alham.pk', PW)
        self.client.force_login(self.admin)
        self.employee = Employee.objects.create(name='Ana Khan', role='counselor', monthly_salary=30000,
                                                joined_on=datetime.date(2024, 1, 1))
        self.day = datetime.date(2026, 10, 21)
        self.url = f'/attendance/record/{self.employee.pk}/2026-10-21/edit/'
        patcher = mock.patch('django.utils.timezone.localdate', return_value=TODAY)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_fix_a_wrong_check_in_time(self):
        record = DailyAttendance.objects.create(employee=self.employee, date=self.day, status='present',
                                                check_in_time=datetime.time(0, 5))
        page = self.client.get(self.url)
        self.assertContains(page, '12:05 AM')
        response = self.client.post(self.url, {'status': 'present', 'check_in_time': '10:40',
                                               'reason': 'Arrived 10:40, phone clock was wrong'})
        self.assertRedirects(response, f'/employees/{self.employee.pk}/?month=10&year=2026', fetch_redirect_response=False)
        record.refresh_from_db()
        self.assertEqual(record.check_in_time, datetime.time(10, 40))
        self.assertTrue(record.is_late)
        self.assertIn('Corrected by HR', record.note)
        entry = AuditLog.objects.get(category='attendance')
        self.assertEqual(entry.changes, {'check_in_time': ['00:05', '10:40']})
        self.assertEqual(entry.actor, self.admin)

    def test_mark_an_unrecorded_day_present(self):
        self.client.post(self.url, {'status': 'present', 'check_in_time': '10:00', 'reason': 'Forgot to check in'})
        record = DailyAttendance.objects.get()
        self.assertEqual(record.status, 'present')
        self.assertFalse(record.is_late)

    def test_change_to_leave_and_back_keeps_leave_records_in_step(self):
        self.client.post(self.url, {'status': 'leave', 'reason': 'Was on approved leave'})
        self.assertTrue(Leave.objects.filter(employee=self.employee, date=self.day).exists())
        self.assertIsNone(DailyAttendance.objects.get().check_in_time)
        self.client.post(self.url, {'status': 'present', 'check_in_time': '10:10', 'reason': 'Came in after all'})
        self.assertFalse(Leave.objects.filter(employee=self.employee, date=self.day).exists())

    def test_present_needs_a_time_and_a_reason(self):
        response = self.client.post(self.url, {'status': 'present', 'check_in_time': '', 'reason': ''})
        self.assertContains(response, 'Enter the time the employee actually arrived')
        self.assertContains(response, 'This field is required')
        self.assertFalse(DailyAttendance.objects.exists())

    def test_future_and_before_joining_are_refused(self):
        response = self.client.get(f'/attendance/record/{self.employee.pk}/2026-11-02/edit/', follow=True)
        self.assertContains(response, 'outside')
        response = self.client.get(f'/attendance/record/{self.employee.pk}/2023-01-02/edit/', follow=True)
        self.assertContains(response, 'outside')
        self.assertEqual(self.client.get(f'/attendance/record/{self.employee.pk}/not-a-date/edit/').status_code, 404)

    def test_warns_when_payroll_needs_regenerating(self):
        Payroll.objects.create(employee=self.employee, month=10, year=2026, base_salary=30000)
        response = self.client.post(self.url, {'status': 'absent', 'reason': 'Was not in office'}, follow=True)
        self.assertContains(response, 'Regenerate it on the Payroll page')

    def test_employees_cannot_edit(self):
        user = User.objects.create_user('ana', password=PW)
        Employee.objects.filter(pk=self.employee.pk).update(user=user)
        self.client.force_login(user)
        self.assertRedirects(self.client.get(self.url), '/attendance/portal/', fetch_redirect_response=False)

    def test_edit_link_on_employee_page(self):
        DailyAttendance.objects.create(employee=self.employee, date=self.day, status='present',
                                       check_in_time=datetime.time(10, 0))
        page = self.client.get(f'/employees/{self.employee.pk}/?month=10&year=2026')
        self.assertContains(page, self.url)
