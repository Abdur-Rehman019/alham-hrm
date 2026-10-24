import datetime
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from attendance.models import DailyAttendance, OfficeLocation, distance_m
from employees.models import Employee

PW = 'Str0ng!Pass#2026'
OFFICE = (31.520370, 74.358749)          # a point in Lahore
NEARBY = (31.520900, 74.358749)          # ~59 m north
FAR = (31.549700, 74.343600)             # ~3.6 km away
OFFICE_IP = '203.0.113.10'


class OfficeLocationRuleTests(TestCase):
    def test_distance(self):
        self.assertAlmostEqual(distance_m(*OFFICE, *NEARBY), 59, delta=2)
        self.assertGreater(distance_m(*OFFICE, *FAR), 3000)

    def test_either_wifi_or_gps_passes_by_default(self):
        loc = OfficeLocation(latitude=Decimal('31.520370'), longitude=Decimal('74.358749'), radius_m=150,
                             allowed_ips=OFFICE_IP)
        self.assertTrue(loc.evaluate(OFFICE_IP)[0])
        self.assertTrue(loc.evaluate('198.51.100.1', *NEARBY, 20)[0])
        ok, reason, distance = loc.evaluate('198.51.100.1', *FAR, 20)
        self.assertFalse(ok)
        self.assertIn('not on office Wi-Fi', reason)
        self.assertIn('km from the office', reason)
        self.assertFalse(loc.evaluate('198.51.100.1')[0])

    def test_require_both(self):
        loc = OfficeLocation(latitude=Decimal('31.520370'), longitude=Decimal('74.358749'), radius_m=150,
                             allowed_ips=OFFICE_IP, require_both=True)
        self.assertFalse(loc.evaluate(OFFICE_IP)[0])
        self.assertFalse(loc.evaluate('198.51.100.1', *NEARBY, 20)[0])
        self.assertTrue(loc.evaluate(OFFICE_IP, *NEARBY, 20)[0])

    def test_gps_accuracy_slack_is_capped(self):
        loc = OfficeLocation(latitude=Decimal('31.520370'), longitude=Decimal('74.358749'), radius_m=150)
        self.assertFalse(loc.evaluate('', *FAR, 5000)[0])


class CheckInLocationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('ana', password=PW)
        self.employee = Employee.objects.create(name='Ana Khan', role='counselor', monthly_salary=30000,
                                                joined_on=datetime.date(2024, 1, 1))
        Employee.objects.filter(pk=self.employee.pk).update(user=self.user)
        self.client.force_login(self.user)

    def _check_in(self, ip='198.51.100.1', position=None, accuracy=20):
        moment = timezone.make_aware(datetime.datetime(2026, 10, 21, 10, 5))
        data = {}
        if position:
            data = {'latitude': position[0], 'longitude': position[1], 'accuracy': accuracy}
        with mock.patch('attendance.employee_portal.timezone.localtime', return_value=moment), \
                mock.patch('attendance.employee_portal.timezone.localdate', return_value=moment.date()):
            response = self.client.post('/attendance/portal/', data, REMOTE_ADDR=ip, follow=True)
        return response, DailyAttendance.objects.get(employee=self.employee)

    def _configure(self, **kwargs):
        OfficeLocation.objects.create(latitude=Decimal('31.520370'), longitude=Decimal('74.358749'), **kwargs)

    def test_not_configured_accepts_and_records_location(self):
        _, record = self._check_in(position=FAR)
        self.assertEqual(record.status, 'present')
        self.assertEqual(record.check_in_ip, '198.51.100.1')
        self.assertEqual(record.check_in_latitude, Decimal('31.549700'))

    def test_inside_radius_is_present(self):
        self._configure()
        _, record = self._check_in(position=NEARBY)
        self.assertEqual(record.status, 'present')
        self.assertLess(record.check_in_distance_m, 150)

    def test_office_wifi_without_location_is_present(self):
        self._configure(allowed_ips=OFFICE_IP)
        _, record = self._check_in(ip=OFFICE_IP)
        self.assertEqual(record.status, 'present')

    def test_far_away_goes_to_review_with_reason(self):
        self._configure(allowed_ips=OFFICE_IP)
        response, record = self._check_in(position=FAR)
        self.assertEqual(record.status, 'needs_review')
        self.assertIn('km from the office', record.note)
        self.assertEqual(record.check_in_time, datetime.time(10, 5))
        self.assertContains(response, 'HR will review it')

    def test_location_refused_goes_to_review(self):
        self._configure()
        _, record = self._check_in()
        self.assertEqual(record.status, 'needs_review')
        self.assertIn('location not shared', record.note)

    def test_hr_approval_keeps_time_and_lateness(self):
        self._configure()
        self._check_in(position=FAR)
        admin = User.objects.create_superuser('boss', 'boss@alham.pk', PW)
        self.client.force_login(admin)
        record = DailyAttendance.objects.get(employee=self.employee)
        page = self.client.get('/imports/attendance/review/')
        self.assertContains(page, 'Where they checked in')
        self.client.post(f'/imports/attendance/review/{record.pk}/resolve/', {'status': 'present'})
        record.refresh_from_db()
        self.assertEqual(record.status, 'present')
        self.assertEqual(record.check_in_time, datetime.time(10, 5))
        self.assertFalse(record.is_late)

    def test_fake_coordinates_are_ignored(self):
        self._configure()
        _, record = self._check_in(position=(999, 74.0))
        self.assertEqual(record.status, 'needs_review')
        self.assertIsNone(record.check_in_latitude)


class OfficeLocationPageTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('boss', 'boss@alham.pk', PW)
        self.client.force_login(self.admin)

    def test_add_current_ip_and_save_location(self):
        self.client.post('/attendance/check-in-location/', {'action': 'add_my_ip'},
                         HTTP_X_FORWARDED_FOR='203.0.113.10', REMOTE_ADDR='10.0.0.1')
        self.assertEqual(OfficeLocation.current().ip_list, ['203.0.113.10'])
        response = self.client.post('/attendance/check-in-location/', {
            'latitude': '31.520370', 'longitude': '74.358749', 'radius_m': '200',
            'allowed_ips': '203.0.113.10\n203.0.113.10\n198.51.100.7',
        })
        self.assertRedirects(response, '/attendance/check-in-location/')
        loc = OfficeLocation.current()
        self.assertEqual(loc.radius_m, 200)
        self.assertEqual(loc.ip_list, ['203.0.113.10', '198.51.100.7'])
        self.assertEqual(OfficeLocation.objects.count(), 1)

    def test_rejects_bad_input(self):
        response = self.client.post('/attendance/check-in-location/', {
            'latitude': '31.5', 'longitude': '', 'radius_m': '5', 'allowed_ips': 'office-wifi'})
        self.assertContains(response, 'not a valid IP address')
        self.assertContains(response, 'between 30 and 2000')
        self.assertFalse(OfficeLocation.objects.exists())

    def test_employees_cannot_open_it(self):
        user = User.objects.create_user('ana', password=PW)
        employee = Employee.objects.create(name='Ana Khan', role='counselor', monthly_salary=30000,
                                           joined_on=datetime.date(2024, 1, 1))
        Employee.objects.filter(pk=employee.pk).update(user=user)
        self.client.force_login(user)
        self.assertRedirects(self.client.get('/attendance/check-in-location/'), '/attendance/portal/',
                             fetch_redirect_response=False)

    def test_review_holiday_button_works(self):
        employee = Employee.objects.create(name='Bob Ali', role='counselor', monthly_salary=30000,
                                           joined_on=datetime.date(2024, 1, 1))
        record = DailyAttendance.objects.create(employee=employee, date=datetime.date(2026, 10, 1), status='needs_review')
        self.client.post(f'/imports/attendance/review/{record.pk}/resolve/', {'status': 'holiday'})
        record.refresh_from_db()
        self.assertEqual(record.status, 'holiday')
