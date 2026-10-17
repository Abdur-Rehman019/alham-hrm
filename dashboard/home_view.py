import calendar
import json

from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Count, Sum
from django.shortcuts import render
from django.utils import timezone

from attendance.models import DailyAttendance, LeaveRequest
from core import analytics
from core.middleware import is_admin_user
from employees.models import Employee
from payroll.models import Payroll, StudentEnrollment

admin_required = user_passes_test(is_admin_user, login_url='login')


@login_required
@admin_required
def dashboard_home(request):
    year, month = analytics.parse_period(request)
    period_label = f"{calendar.month_name[month]} {year}"
    staff = list(Employee.objects.filter(is_active=True).order_by('name'))

    enrollments = StudentEnrollment.objects.filter(confirmed_on__year=year, confirmed_on__month=month)
    incentives_total = enrollments.aggregate(t=Sum('incentive_amount'))['t'] or 0
    payroll_total = Payroll.objects.filter(year=year, month=month).aggregate(t=Sum('net_pay'))['t'] or 0

    # Counselor of the month: most enrollments in the selected month
    top = enrollments.values('counselor').annotate(c=Count('id')).order_by('-c').first()
    counselor_of_month = Employee.objects.filter(pk=top['counselor']).first() if top else None

    top_month = list(enrollments.values('counselor__name').annotate(c=Count('id')).order_by('-c')[:6])
    countries, country_counts = analytics.country_breakdown(enrollments)
    roles = list(Employee.objects.filter(is_active=True).values('role').annotate(c=Count('id')).order_by('role'))
    role_names = dict(Employee.ROLE_CHOICES)

    # Per-employee attendance for the month (also drives the rate chart and the details table)
    rows = []
    for e in staff:
        s = analytics.attendance_summary(e, year, month)
        rows.append({'employee': e, **s})

    # 6-month organisation-wide trends
    months, enroll_trend, incentive_trend, rate_trend = [], [], [], []
    for y, m in analytics.back_months(year, month, 6):
        qs = StudentEnrollment.objects.filter(confirmed_on__year=y, confirmed_on__month=m)
        months.append(analytics.month_label(y, m))
        enroll_trend.append(qs.count())
        incentive_trend.append(float(qs.aggregate(t=Sum('incentive_amount'))['t'] or 0))
        present = working = 0
        for e in staff:
            s = analytics.attendance_summary(e, y, m)
            present += s['present']
            working += s['working_days']
        rate_trend.append(min(100, round(present * 100 / working)) if working else None)

    daily = analytics.daily_overview(year, month)
    rated = [r for r in rows if r['rate'] is not None]
    charts = {
        'months': months, 'enroll_trend': enroll_trend, 'incentive_trend': incentive_trend, 'rate_trend': rate_trend,
        'top_names': [t['counselor__name'] for t in top_month], 'top_counts': [t['c'] for t in top_month],
        'countries': countries, 'country_counts': country_counts,
        'role_labels': [role_names.get(r['role'], r['role']) for r in roles], 'role_counts': [r['c'] for r in roles],
        'daily': daily,
        'rate_names': [r['employee'].name for r in rated], 'rate_values': [r['rate'] for r in rated],
    }
    return render(request, 'dashboard/home.html', {
        'year': year, 'month': month, 'period_label': period_label, 'options': analytics.month_options(),
        'total_employees': len(staff), 'enrollment_count': enrollments.count(),
        'incentives_total': incentives_total, 'payroll_total': payroll_total,
        'pending_leaves': LeaveRequest.objects.filter(status='pending').count(),
        'needs_review': DailyAttendance.objects.filter(status='needs_review').count(),
        'counselor_of_month': counselor_of_month, 'counselor_of_month_count': top['c'] if top else 0,
        'attendance_rows': rows, 'charts': charts,
        'has_trend': any(enroll_trend) or any(incentive_trend), 'has_top': bool(top_month),
        'has_countries': bool(countries), 'has_roles': bool(roles),
        'has_daily': any(v for key in ('present', 'leave', 'absent') for v in daily[key] if v),
        'has_rates': bool(rated), 'has_rate_trend': any(v is not None for v in rate_trend),
    })