from django.test import TestCase

# Create your tests here.
import datetime
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from attendance.models import DailyAttendance, Leave, LeaveRequest
from core import analytics
from employees.forms import EmployeeForm
from employees.models import Employee
from payroll.models import IncentiveRule, Payroll, StudentEnrollment

PW = 'Str0ng!Pass#2026'


def make_employee(name, username=None, **kw):
    e = Employee.objects.create(name=name, role=kw.pop('role', 'counselor'), monthly_salary=kw.pop('salary', 30000),
                                joined_on=kw.pop('joined_on', datetime.date(2024, 1, 1)), **kw)
    if username:
        u = User.objects.create_user(username, password=PW)
        Employee.objects.filter(pk=e.pk).update(user=u)
        e.refresh_from_db()
    return e


def next_weekday(day=0, after=None):
    d = (after or timezone.localdate()) + datetime.timedelta(days=1)
    while d.weekday() != day:
        d += datetime.timedelta(days=1)
    return d


class Base(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('boss', 'b@x.com', PW)
        self.ana = make_employee('Ana Khan', 'ana')
        self.bob = make_employee('Bob Ali', 'bob')
        self.client_admin = self.client_class()
        self.client_admin.force_login(self.admin)
        self.ana_c = self.client_class()
        self.ana_c.force_login(self.ana.user)
        self.bob_c = self.client_class()
        self.bob_c.force_login(self.bob.user)


class SecurityTests(Base):
    def test_employee_locked_to_portal(self):
        for url in ['/', '/employees/', '/payroll/generate/', '/attendance/', '/attendance/leave-requests/', '/imports/enrollments/']:
            r = self.ana_c.get(url)
            self.assertRedirects(r, '/attendance/portal/', fetch_redirect_response=False, msg_prefix=url)

    def test_forced_password_change(self):
        Employee.objects.filter(pk=self.ana.pk).update(must_change_password=True)
        r = self.ana_c.get('/attendance/portal/')
        self.assertRedirects(r, '/accounts/change-password/', fetch_redirect_response=False)
        # same password is refused
        r = self.ana_c.post('/accounts/change-password/', {'old_password': PW, 'new_password1': PW, 'new_password2': PW})
        self.assertEqual(r.status_code, 200)
        self.ana.refresh_from_db()
        self.assertTrue(self.ana.must_change_password)
        # weak password refused
        r = self.ana_c.post('/accounts/change-password/', {'old_password': PW, 'new_password1': '12345678', 'new_password2': '12345678'})
        self.assertEqual(r.status_code, 200)
        # a good one works, flag clears, portal opens, user stays signed in
        r = self.ana_c.post('/accounts/change-password/', {'old_password': PW, 'new_password1': 'Another#Pass77', 'new_password2': 'Another#Pass77'})
        self.assertEqual(r.status_code, 302)
        self.ana.refresh_from_db()
        self.assertFalse(self.ana.must_change_password)
        self.assertEqual(self.ana_c.get('/attendance/portal/').status_code, 200)

    def test_create_login_flags_must_change_and_blocks_inactive(self):
        carl = make_employee('Carl Raza')
        r = self.client_admin.post(f'/employees/{carl.pk}/create-login/', {'username': 'carl', 'password1': PW, 'password2': PW})
        self.assertEqual(r.status_code, 302)
        carl.refresh_from_db()
        self.assertTrue(carl.must_change_password)
        self.assertEqual(carl.user.username, 'carl')
        dan = make_employee('Dan Iqbal', is_active=False)
        self.client_admin.post(f'/employees/{dan.pk}/create-login/', {'username': 'dan', 'password1': PW, 'password2': PW})
        self.assertFalse(User.objects.filter(username='dan').exists())

    def test_weak_or_duplicate_login_rejected(self):
        carl = make_employee('Carl Raza')
        r = self.client_admin.post(f'/employees/{carl.pk}/create-login/', {'username': 'ana', 'password1': PW, 'password2': PW})
        self.assertContains(r, 'already taken')
        r = self.client_admin.post(f'/employees/{carl.pk}/create-login/', {'username': 'carl', 'password1': 'password', 'password2': 'password'})
        self.assertFalse(User.objects.filter(username='carl').exists())

    def test_reset_password_issues_temp_and_forces_change(self):
        r = self.client_admin.post(f'/employees/{self.ana.pk}/reset-password/')
        self.assertEqual(r.status_code, 200)
        temp = r.context['temp']
        self.ana.refresh_from_db()
        self.assertTrue(self.ana.must_change_password)
        self.assertTrue(self.ana.user.check_password(temp))
        self.assertEqual(self.client_admin.get(f'/employees/{self.ana.pk}/reset-password/').status_code, 405)

    def test_employee_cannot_reset_or_approve(self):
        self.assertRedirects(self.ana_c.post(f'/employees/{self.bob.pk}/reset-password/'), '/attendance/portal/', fetch_redirect_response=False)
        lr = LeaveRequest.objects.create(employee=self.bob, date=next_weekday(0), reason='x y z')
        self.ana_c.post(f'/attendance/leave-requests/{lr.pk}/approve/')
        lr.refresh_from_db()
        self.assertEqual(lr.status, 'pending')

    def test_state_changes_need_post(self):
        lr = LeaveRequest.objects.create(employee=self.bob, date=next_weekday(0), reason='x y z')
        self.assertEqual(self.client_admin.get(f'/attendance/leave-requests/{lr.pk}/approve/').status_code, 405)
        self.assertEqual(self.client_admin.get(f'/attendance/leave-requests/{lr.pk}/reject/').status_code, 405)

    def test_employees_cannot_download_payslips(self):
        p_ana = Payroll.objects.create(employee=self.ana, month=1, year=2026, base_salary=30000)
        r = self.ana_c.get(f'/attendance/my-payslip/{p_ana.pk}/')
        self.assertEqual(r.status_code, 404)
        self.assertRedirects(self.ana_c.get(f'/payroll/payslip/{p_ana.pk}/'), '/attendance/portal/', fetch_redirect_response=False)

    def test_login_follows_employment_status(self):
        self.client_admin.post(f'/employees/{self.ana.pk}/deactivate/')
        self.ana.user.refresh_from_db()
        self.assertFalse(self.ana.user.is_active)
        self.assertRedirects(self.ana_c.get('/attendance/portal/'), '/accounts/login/?next=/attendance/portal/', fetch_redirect_response=False)
        self.client_admin.post(f'/employees/{self.ana.pk}/terminate/', {'leaving_date': timezone.localdate().isoformat()})
        self.ana.refresh_from_db()
        self.assertFalse(self.ana.is_active)
        self.assertFalse(self.ana.user.is_active)

    def test_reactivation_clears_leaving_date_and_restores_login(self):
        self.client_admin.post(f'/employees/{self.ana.pk}/terminate/', {'leaving_date': timezone.localdate().isoformat()})
        self.ana.refresh_from_db()
        self.assertIsNotNone(self.ana.leaving_date)
        form = EmployeeForm({'name': 'Ana Khan', 'role': 'counselor', 'monthly_salary': '30000', 'joined_on': '2024-01-01',
                             'is_active': 'on', 'leaving_date': timezone.localdate().isoformat()}, instance=self.ana)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        self.ana.refresh_from_db()
        self.assertTrue(self.ana.is_active)
        self.assertIsNone(self.ana.leaving_date)
        self.assertTrue(self.ana.user.is_active)


class CheckInTests(Base):
    def test_check_in_records_local_time_once(self):
        if timezone.localdate().weekday() == 6:
            self.skipTest('Sunday')
        before = timezone.localtime().time().replace(microsecond=0)
        self.ana_c.post('/attendance/portal/attendance/', {'action': 'check_in'})
        self.ana_c.post('/attendance/portal/attendance/', {'action': 'check_in'})
        rows = DailyAttendance.objects.filter(employee=self.ana)
        self.assertEqual(rows.count(), 1)
        t, now = rows.first().check_in_time, timezone.localtime().time()
        self.assertGreaterEqual(t, before)
        self.assertLessEqual(t, now)

    def test_sunday_blocked(self):
        sunday = next_weekday(6)
        with mock.patch('django.utils.timezone.localdate', return_value=sunday):
            self.ana_c.post('/attendance/portal/attendance/', {'action': 'check_in'})
        self.assertFalse(DailyAttendance.objects.filter(employee=self.ana).exists())

    def test_inactive_cannot_check_in(self):
        Employee.objects.filter(pk=self.ana.pk).update(is_active=False)
        self.ana_c.post('/attendance/portal/attendance/', {'action': 'check_in'})
        self.assertFalse(DailyAttendance.objects.filter(employee=self.ana).exists())


class LeaveFlowTests(Base):
    def req(self, client, day, reason='Family event'):
        return client.post('/attendance/portal/leaves/', {'date': day.isoformat(), 'reason': reason})

    def test_request_validations(self):
        today = timezone.localdate()
        monday = next_weekday(0)
        self.req(self.ana_c, today - datetime.timedelta(days=1))                      # past
        self.req(self.ana_c, next_weekday(6))                                          # Sunday
        self.req(self.ana_c, today + datetime.timedelta(days=90))                      # too far
        self.req(self.ana_c, monday, reason='  ')                                      # no reason
        self.assertEqual(LeaveRequest.objects.count(), 0)
        self.req(self.ana_c, monday)
        self.req(self.ana_c, monday)                                                   # duplicate
        self.assertEqual(LeaveRequest.objects.filter(employee=self.ana).count(), 1)

    def test_approve_creates_leave_and_attendance_and_is_idempotent(self):
        monday = next_weekday(0)
        self.req(self.ana_c, monday)
        lr = LeaveRequest.objects.get()
        self.client_admin.post(f'/attendance/leave-requests/{lr.pk}/approve/')
        self.client_admin.post(f'/attendance/leave-requests/{lr.pk}/approve/')
        lr.refresh_from_db()
        self.assertEqual(lr.status, 'approved')
        self.assertEqual(Leave.objects.filter(employee=self.ana, date=monday).count(), 1)
        self.assertEqual(DailyAttendance.objects.get(employee=self.ana, date=monday).status, 'leave')
        self.req(self.ana_c, monday)                                                   # already on leave
        self.assertEqual(LeaveRequest.objects.filter(employee=self.ana).count(), 1)

    def test_cannot_approve_when_already_present(self):
        monday = next_weekday(0)
        self.req(self.ana_c, monday)
        DailyAttendance.objects.create(employee=self.ana, date=monday, status='present')
        lr = LeaveRequest.objects.get()
        self.client_admin.post(f'/attendance/leave-requests/{lr.pk}/approve/')
        lr.refresh_from_db()
        self.assertEqual(lr.status, 'pending')
        self.assertFalse(Leave.objects.exists())

    def test_reject_and_cancel(self):
        monday = next_weekday(0)
        self.req(self.ana_c, monday)
        lr = LeaveRequest.objects.get()
        self.client_admin.post(f'/attendance/leave-requests/{lr.pk}/reject/', {'note': 'Busy week'})
        lr.refresh_from_db()
        self.assertEqual((lr.status, lr.decision_note), ('rejected', 'Busy week'))
        self.req(self.ana_c, monday + datetime.timedelta(days=1))
        lr2 = LeaveRequest.objects.get(status='pending')
        self.bob_c.post(f'/attendance/my-leave-requests/{lr2.pk}/cancel/')            # not his
        lr2.refresh_from_db()
        self.assertEqual(lr2.status, 'pending')
        self.ana_c.post(f'/attendance/my-leave-requests/{lr2.pk}/cancel/')
        lr2.refresh_from_db()
        self.assertEqual(lr2.status, 'cancelled')

    def test_free_leaves_then_deduction_and_recompute_on_delete(self):
        base = datetime.date(2026, 3, 2)
        leaves = [Leave.objects.create(employee=self.ana, date=base + datetime.timedelta(days=i)) for i in range(3)]
        self.assertEqual([l.is_deducted for l in leaves], [False, False, True])
        self.client_admin.post(f'/attendance/{leaves[0].pk}/delete/')
        leaves[2].refresh_from_db(); leaves[1].refresh_from_db()
        self.assertFalse(leaves[1].is_deducted)
        self.assertFalse(leaves[2].is_deducted)

    def test_checking_in_cancels_pending_request_for_today(self):
        today = timezone.localdate()
        if today.weekday() == 6:
            self.skipTest('Sunday')
        LeaveRequest.objects.create(employee=self.ana, date=today, reason='maybe')
        self.ana_c.post('/attendance/portal/attendance/', {'action': 'check_in'})
        self.assertEqual(LeaveRequest.objects.get().status, 'cancelled')

    def test_admin_added_leave_creates_attendance_row(self):
        d = datetime.date(2026, 3, 3)
        r = self.client_admin.post('/attendance/add/', {'employee': self.ana.pk, 'date': d.isoformat(), 'leave_type': 'casual', 'reason': 'x'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(DailyAttendance.objects.get(employee=self.ana, date=d).status, 'leave')


class HolidayTests(Base):
    def test_holiday_marks_active_staff_but_not_people_who_came_in(self):
        day = datetime.date(2026, 3, 4)
        DailyAttendance.objects.create(employee=self.bob, date=day, status='present', check_in_time=datetime.time(10, 0))
        gone = make_employee('Zed Gone', is_active=False)
        r = self.client_admin.post('/attendance/holiday/', {'date': day.isoformat(), 'name': 'Test Day'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(DailyAttendance.objects.get(employee=self.ana, date=day).status, 'holiday')
        self.assertEqual(DailyAttendance.objects.get(employee=self.bob, date=day).status, 'present')
        self.assertFalse(DailyAttendance.objects.filter(employee=gone, date=day).exists())
        self.client_admin.post('/attendance/holiday/', {'date': day.isoformat()})          # repeat is harmless
        self.assertEqual(DailyAttendance.objects.filter(date=day).count(), 2)

    def test_bad_date_and_employee_access(self):
        self.client_admin.post('/attendance/holiday/', {'date': 'nope'})
        self.assertFalse(DailyAttendance.objects.exists())
        self.ana_c.post('/attendance/holiday/', {'date': '2026-03-04'})
        self.assertFalse(DailyAttendance.objects.exists())


class AnalyticsTests(Base):
    TODAY = datetime.date(2026, 9, 17)

    def test_absent_is_computed_for_unrecorded_working_days(self):
        emp = make_employee('Eve Noor', joined_on=datetime.date(2026, 9, 1))
        for d in (1, 2, 3):
            DailyAttendance.objects.create(employee=emp, date=datetime.date(2026, 9, d), status='present', check_in_time=datetime.time(11, 0))
        DailyAttendance.objects.create(employee=emp, date=datetime.date(2026, 9, 4), status='leave')
        Leave.objects.create(employee=emp, date=datetime.date(2026, 9, 5))          # legacy leave, no attendance row
        with mock.patch('django.utils.timezone.localdate', return_value=self.TODAY):
            s = analytics.attendance_summary(emp, 2026, 9)
        expected = [d for d in range(1, 17) if datetime.date(2026, 9, d).weekday() != 6]   # today excluded
        self.assertEqual(s['working_days'], len(expected))
        self.assertEqual((s['present'], s['leave']), (3, 2))
        self.assertEqual(s['absent'], len(expected) - 5)
        self.assertEqual(s['rate'], round(3 * 100 / len(expected)))
        self.assertEqual(s['avg_checkin'], '11:00 AM')

    def test_today_without_record_is_not_absent_and_new_joiner_not_penalised(self):
        emp = make_employee('Fay Shah', joined_on=self.TODAY)
        with mock.patch('django.utils.timezone.localdate', return_value=self.TODAY):
            s = analytics.attendance_summary(emp, 2026, 9)
        self.assertEqual((s['absent'], s['working_days'], s['rate']), (0, 0, None))

    def test_holiday_rows_are_excluded_from_working_days(self):
        emp = make_employee('Gus Mir', joined_on=datetime.date(2026, 9, 1))
        DailyAttendance.objects.create(employee=emp, date=datetime.date(2026, 9, 2), status='holiday')
        with mock.patch('django.utils.timezone.localdate', return_value=self.TODAY):
            s = analytics.attendance_summary(emp, 2026, 9)
            self.assertEqual(s['absent'], s['working_days'])
            self.assertEqual(s['holiday'], 1)

    def test_departed_employee_not_counted_after_leaving(self):
        emp = make_employee('Hal Dar', joined_on=datetime.date(2026, 9, 1), leaving_date=datetime.date(2026, 9, 5), is_active=False)
        with mock.patch('django.utils.timezone.localdate', return_value=self.TODAY):
            s = analytics.attendance_summary(emp, 2026, 9)
        self.assertEqual(s['working_days'], 5 - sum(1 for d in range(1, 6) if datetime.date(2026, 9, d).weekday() == 6))

    def test_period_parsing_is_safe(self):
        class R:
            def __init__(self, **g): self.GET = g
        today = timezone.localdate()
        for bad in ({'month': '13'}, {'month': 'x'}, {'year': '1900'}, {'year': '9999', 'month': '1'}, {'month': '0'}):
            self.assertEqual(analytics.parse_period(R(**bad)), (today.year, today.month), bad)


class PageSmokeTests(Base):
    def seed(self):
        IncentiveRule.objects.create(destination_country='Turkey', amount=10000)
        today = timezone.localdate()
        StudentEnrollment.objects.create(student_name='Stu One', destination_country='Turkey', counselor=self.ana, confirmed_on=today)
        DailyAttendance.objects.create(employee=self.ana, date=today, status='present', check_in_time=datetime.time(10, 55))
        Payroll.objects.create(employee=self.ana, month=today.month, year=today.year, base_salary=30000)

    def test_admin_pages_render_empty_and_seeded(self):
        urls = ['/', '/?month=13&year=abc', '/?month=1&year=2020', '/employees/', f'/employees/{self.ana.pk}/',
                f'/employees/{self.ana.pk}/?month=2&year=2026', '/attendance/', '/attendance/leave-requests/',
                '/payroll/generate/', '/payroll/incentive-rules/', '/payroll/enrollments/', '/imports/attendance/review/']
        for label in ('empty', 'seeded'):
            if label == 'seeded':
                self.seed()
            for u in urls:
                self.assertEqual(self.client_admin.get(u).status_code, 200, f'{label} {u}')

    def test_employee_portal_renders_for_every_state(self):
        for label in ('empty', 'seeded'):
            if label == 'seeded':
                self.seed()
            for u in ['/attendance/portal/', '/attendance/portal/attendance/?month=1&year=2020', '/attendance/portal/attendance/?month=99']:
                self.assertEqual(self.ana_c.get(u).status_code, 200, f'{label} {u}')

    def test_user_without_employee_record_is_handled(self):
        stray = User.objects.create_user('stray', password=PW)
        c = self.client_class(); c.force_login(stray)
        self.assertContains(c.get('/attendance/portal/'), 'not linked')
        self.assertEqual(c.get('/employees/').status_code, 302)

    def test_logout_is_post_only(self):
        html = self.client_admin.get('/').content.decode()
        self.assertIn('method="post" action="/accounts/logout/"', html)
        self.assertEqual(self.client_admin.get('/accounts/logout/').status_code, 405)
        self.assertEqual(self.client_admin.post('/accounts/logout/').status_code, 302)