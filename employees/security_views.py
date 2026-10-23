import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from attendance.models import FREE_LEAVES_PER_MONTH
from core import analytics
from core.middleware import is_admin_user
from .forms import CreateLoginForm
from .models import Employee

admin_required = user_passes_test(is_admin_user, login_url='login')


@login_required
@admin_required
def employee_detail(request, pk):
    """Admin view of one employee: details, attendance and performance for a chosen month."""
    employee = get_object_or_404(Employee, pk=pk)
    year, month = analytics.parse_period(request)
    summary = analytics.attendance_summary(employee, year, month)
    trends = analytics.employee_trends(employee, year, month)
    month_enrollments = employee.enrollments.filter(
        confirmed_on__year=year, confirmed_on__month=month).order_by('-confirmed_on')
    countries, country_counts = analytics.country_breakdown(employee.enrollments.all())
    day_labels, day_minutes = analytics.checkin_series(employee, year, month)
    payrolls = list(employee.payrolls.all()[:6])
    leaves = employee.leaves.filter(date__year=year, date__month=month)

    charts = {
        'months': trends['months'], 'enrollments': trends['enrollments'], 'incentives': trends['incentives'],
        'present': trends['present'], 'leave': trends['leave'], 'absent': trends['absent'], 'rate': trends['rate'],
        'countries': countries, 'country_counts': country_counts,
        'checkin_days': day_labels, 'checkin_minutes': day_minutes,
        'pay_months': [f"{p.month}/{p.year}" for p in reversed(payrolls)],
        'pay_net': [float(p.net_pay) for p in reversed(payrolls)],
    }
    return render(request, 'employees/employee_detail.html', {
        'employee': employee, 'year': year, 'month': month,
        'period_label': f"{analytics.calendar.month_name[month]} {year}",
        'options': analytics.month_options(),
        'summary': summary, 'charts': charts,
        'month_enrollments': month_enrollments,
        'month_incentive': month_enrollments.aggregate(t=Sum('incentive_amount'))['t'] or 0,
        'attendance_log': analytics.attendance_log(employee, year, month),
        'leaves_used': leaves.count(), 'leaves_deducted': leaves.filter(is_deducted=True).count(),
        'free_leaves': FREE_LEAVES_PER_MONTH,
        'leave_requests': employee.leave_requests.all()[:10],
        'payrolls': payrolls,
        'has_enrollments': any(trends['enrollments']), 'has_attendance': any(trends['present']) or any(trends['leave']) or any(trends['absent']),
        'has_checkins': bool(day_minutes), 'has_countries': bool(countries), 'has_pay': bool(payrolls),
    })


@login_required
@admin_required
def employee_create_login(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if employee.user_id:
        messages.info(request, f"{employee.name} already has a login.")
        return redirect('employee_detail', pk=employee.pk)
    if not employee.is_active:
        messages.error(request, "Cannot create a login for an inactive employee.")
        return redirect('employee_detail', pk=employee.pk)

    form = CreateLoginForm(request.POST or None, initial={'email': employee.email or ''})
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            user = User.objects.create_user(
                username=form.cleaned_data['username'],
                email=form.cleaned_data.get('email') or employee.email or '',
                password=form.cleaned_data['password1'], is_staff=False,
            )
            # update() avoids re-running full model validation on older employee records
            Employee.objects.filter(pk=employee.pk).update(user=user, must_change_password=True)
        messages.success(request, f"Login created for {employee.name}. They must set a new password at first sign-in.")
        return redirect('employee_detail', pk=employee.pk)
    return render(request, 'employees/employee_create_login.html', {'form': form, 'employee': employee})


@login_required
@admin_required
@require_POST
def employee_reset_password(request, pk):
    """Issue a one-time temporary password (also clears any brute-force lockout)."""
    employee = get_object_or_404(Employee, pk=pk)
    if not employee.user_id:
        messages.error(request, "This employee has no login yet.")
        return redirect('employee_detail', pk=employee.pk)
    temp = secrets.token_urlsafe(9)
    user = employee.user
    user.set_password(temp)
    user.save()
    Employee.objects.filter(pk=employee.pk).update(must_change_password=True)
    from axes.utils import reset
    reset(username=user.username)
    # Rendered directly (not stored in a cookie/session) so it is shown exactly once.
    return render(request, 'employees/employee_temp_password.html', {'employee': employee, 'username': user.username, 'temp': temp})