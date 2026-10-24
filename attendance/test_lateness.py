import datetime
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from attendance.models import DailyAttendance, is_late_check_in
from employees.models import Employee

PW = 'Str0ng!Pass#2026'


class LatenessRuleTests(TestCase):
    def test_margin_until_1015(self):
        t = datetime.time
        self.assertFalse(is_late_check_in(t(9, 40)))
        self.assertFalse(is_late_check_in(t(10, 0)))
        self.assertFalse(is_late_check_in(t(10, 15)))
        self.assertFalse(is_late_check_in(t(10, 15, 59)))
        self.assertTrue(is_late_check_in(t(10, 16)))
        self.assertTrue(is_late_check_in('11:05:00'))
        self.assertFalse(is_late_check_in(None))

    def test_saved_records_follow_the_rule(self):
        employee = Employee.objects.create(name='Ana Khan', role='counselor', monthly_salary=30000,
                                           joined_on=datetime.date(2024, 1, 1))
        day = datetime.date(2026, 10, 1)
        late = DailyAttendance.objects.create(employee=employee, date=day, status='present',
                                              check_in_time=datetime.time(10, 30))
        on_time = DailyAttendance.objects.create(employee=employee, date=day + datetime.timedelta(days=1),
                                                 status='present', check_in_time=datetime.time(10, 10))
        self.assertTrue(late.is_late)
        self.assertFalse(on_time.is_late)
        late.check_in_time = datetime.time(10, 5)
        late.save(update_fields=['check_in_time'])
        late.refresh_from_db()
        self.assertFalse(late.is_late)


class SelfCheckInTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ana', password=PW)
        self.employee = Employee.objects.create(name='Ana Khan', role='counselor', monthly_salary=30000,
                                                joined_on=datetime.date(2024, 1, 1))
        Employee.objects.filter(pk=self.employee.pk).update(user=self.user)
        self.client.force_login(self.user)

    def _check_in_at(self, hour, minute):
        # A Wednesday, so the Sunday rule does not interfere.
        moment = timezone.make_aware(datetime.datetime(2026, 10, 21, hour, minute))
        with mock.patch('attendance.employee_portal.timezone.localtime', return_value=moment), \
                mock.patch('attendance.employee_portal.timezone.localdate', return_value=moment.date()):
            return self.client.post('/attendance/portal/', follow=True)

    def test_late_check_in_is_flagged_and_explained(self):
        response = self._check_in_at(10, 40)
        record = DailyAttendance.objects.get(employee=self.employee)
        self.assertTrue(record.is_late)
        self.assertContains(response, 'recorded as late')

    def test_on_time_within_margin(self):
        self._check_in_at(10, 15)
        self.assertFalse(DailyAttendance.objects.get(employee=self.employee).is_late)

    def test_no_check_in_after_office_hours(self):
        response = self._check_in_at(18, 5)
        self.assertFalse(DailyAttendance.objects.filter(employee=self.employee).exists())
        self.assertContains(response, 'Office hours are over')
