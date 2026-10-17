"""Shared calculations used by the dashboard, the admin employee page and the employee portal."""
import calendar
import datetime
from collections import defaultdict

from django.db.models import Count, Sum
from django.utils import timezone


def back_months(year, month, n=6):
    """The n months ending at (year, month), oldest first."""
    out = []
    for i in range(n - 1, -1, -1):
        m, y = month - i, year
        while m <= 0:
            m += 12
            y -= 1
        out.append((y, m))
    return out


def month_label(year, month):
    return f"{calendar.month_abbr[month]} {year}"


def month_bounds(year, month):
    return datetime.date(year, month, 1), datetime.date(year, month, calendar.monthrange(year, month)[1])


def parse_period(request):
    """Reads ?month=&year= safely. Falls back to the current month on any bad or future value."""
    today = timezone.localdate()
    try:
        year = int(request.GET.get('year', today.year))
        month = int(request.GET.get('month', today.month))
        if not (1 <= month <= 12) or year < 2015 or (year, month) > (today.year, today.month):
            raise ValueError
    except (TypeError, ValueError):
        year, month = today.year, today.month
    return year, month


def month_options(n=12):
    today = timezone.localdate()
    return [
        {'year': y, 'month': m, 'label': f"{calendar.month_name[m]} {y}"}
        for y, m in reversed(back_months(today.year, today.month, n))
    ]


def _expected_dates(employee, year, month):
    """Days this employee was expected to work: Mon-Sat, from joining until today or leaving."""
    start, end = month_bounds(year, month)
    today = timezone.localdate()
    start = max(start, employee.joined_on)
    end = min(end, today, employee.leaving_date or end)
    out, d = [], start
    while d <= end:
        if d.weekday() != 6:
            out.append(d)
        d += datetime.timedelta(days=1)
    return out


def attendance_summary(employee, year, month):
    """
    Present / leave / absent for one month. A working day with no record at all counts as
    absent (today is never counted absent, the day is not over). Sundays are never expected.
    """
    today = timezone.localdate()
    rows = list(employee.daily_attendance.filter(date__year=year, date__month=month))
    by_date = {r.date: r for r in rows}
    counts = defaultdict(int)
    for r in rows:
        counts[r.status] += 1

    leave_dates = set(employee.leaves.filter(date__year=year, date__month=month).values_list('date', flat=True))
    expected = [d for d in _expected_dates(employee, year, month) if d != today or d in by_date]
    unrecorded_leave = [d for d in expected if d not in by_date and d in leave_dates]
    unrecorded = [d for d in expected if d not in by_date and d not in leave_dates]
    working = len([d for d in expected if d not in by_date or by_date[d].status != 'holiday'])

    times = [r.check_in_time for r in rows if r.status == 'present' and r.check_in_time]
    avg_checkin = None
    if times:
        avg = sum(t.hour * 60 + t.minute for t in times) // len(times)
        avg_checkin = datetime.time(avg // 60, avg % 60).strftime('%I:%M %p').lstrip('0')

    present = counts['present']
    return {
        'present': present,
        'leave': counts['leave'] + len(unrecorded_leave),
        'absent': counts['absent'] + len(unrecorded),
        'holiday': counts['holiday'],
        'needs_review': counts['needs_review'],
        'late': sum(1 for r in rows if r.is_late),
        'avg_checkin': avg_checkin,
        'working_days': working,
        'rate': min(100, round(present * 100 / working)) if working else None,
    }


def attendance_log(employee, year, month):
    """Every recorded day plus unrecorded working days (shown as absent), newest first."""
    today = timezone.localdate()
    by_date = {r.date: r for r in employee.daily_attendance.filter(date__year=year, date__month=month)}
    log = [
        {'date': r.date, 'status': r.status, 'check_in': r.check_in_time, 'late': r.is_late,
         'note': r.note, 'unrecorded': False}
        for r in by_date.values()
    ]
    leave_dates = set(employee.leaves.filter(date__year=year, date__month=month).values_list('date', flat=True))
    for d in _expected_dates(employee, year, month):
        if d in by_date or d == today:
            continue
        if d in leave_dates:
            log.append({'date': d, 'status': 'leave', 'check_in': None, 'late': False,
                        'note': 'Approved leave', 'unrecorded': False})
        else:
            log.append({'date': d, 'status': 'absent', 'check_in': None, 'late': False,
                        'note': 'No check-in recorded', 'unrecorded': True})
    return sorted(log, key=lambda x: x['date'], reverse=True)


def checkin_series(employee, year, month):
    """(day labels, minutes after midnight) for days with a check-in time, for the punctuality chart."""
    rows = employee.daily_attendance.filter(
        date__year=year, date__month=month, status='present', check_in_time__isnull=False
    ).order_by('date')
    return [str(r.date.day) for r in rows], [r.check_in_time.hour * 60 + r.check_in_time.minute for r in rows]


def employee_trends(employee, year, month, n=6):
    from payroll.models import StudentEnrollment
    t = {'months': [], 'enrollments': [], 'incentives': [], 'present': [], 'leave': [], 'absent': [], 'rate': []}
    for y, m in back_months(year, month, n):
        qs = StudentEnrollment.objects.filter(counselor=employee, confirmed_on__year=y, confirmed_on__month=m)
        s = attendance_summary(employee, y, m)
        t['months'].append(month_label(y, m))
        t['enrollments'].append(qs.count())
        t['incentives'].append(float(qs.aggregate(x=Sum('incentive_amount'))['x'] or 0))
        t['present'].append(s['present'])
        t['leave'].append(s['leave'])
        t['absent'].append(s['absent'])
        t['rate'].append(s['rate'])
    return t


def country_breakdown(qs):
    rows = qs.values('destination_country').annotate(c=Count('id')).order_by('-c')
    return [r['destination_country'] for r in rows], [r['c'] for r in rows]


def daily_overview(year, month):
    """Per-day present / leave / absent across all staff for the month (None for days not yet reached)."""
    from attendance.models import DailyAttendance, Leave
    from employees.models import Employee

    start, end = month_bounds(year, month)
    today = timezone.localdate()
    staff = list(Employee.objects.filter(joined_on__lte=end))
    tally = defaultdict(lambda: defaultdict(int))
    for r in DailyAttendance.objects.filter(date__range=(start, end)).values('date', 'status').annotate(c=Count('id')):
        tally[r['date']][r['status']] = r['c']

    leave_by_day = defaultdict(set)
    for emp_id, d in DailyAttendance.objects.filter(date__range=(start, end), status='leave').values_list('employee_id', 'date'):
        leave_by_day[d].add(emp_id)
    for emp_id, d in Leave.objects.filter(date__range=(start, end)).values_list('employee_id', 'date'):
        leave_by_day[d].add(emp_id)

    out = {'days': [], 'present': [], 'leave': [], 'absent': []}
    d = start
    while d <= end:
        out['days'].append(str(d.day))
        t = tally.get(d, {})
        if d > today:
            out['present'].append(None); out['leave'].append(None); out['absent'].append(None)
        else:
            absent = t.get('absent', 0)
            if d < today and not (d.weekday() == 6 and not t.get('present')):
                expected = sum(1 for e in staff if e.joined_on <= d and (e.leaving_date is None or e.leaving_date >= d))
                absent = max(absent, expected - t.get('present', 0) - len(leave_by_day.get(d, ()))
                             - t.get('holiday', 0) - t.get('needs_review', 0))
            out['present'].append(t.get('present', 0))
            out['leave'].append(len(leave_by_day.get(d, ())))
            out['absent'].append(absent)
        d += datetime.timedelta(days=1)
    return out