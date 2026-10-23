from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from core import analytics
from employees.models import Employee
from payroll.calculations import compute_payroll
from payroll.models import Payroll, StudentEnrollment

from .forms import LeaveRequestForm
from .models import DailyAttendance, Leave, LeaveRequest


def _employee(request):
    return getattr(request.user, 'employee_profile', None)


def _period(request):
    return analytics.parse_period(request)


def _trends(employee, year, month):
    return analytics.employee_trends(employee, year, month)


def _attendance_charts(employee, year, month):
    trends = _trends(employee, year, month)
    days, checkins = analytics.checkin_series(employee, year, month)
    return {
        'months': trends['months'],
        'present': trends['present'],
        'leave': trends['leave'],
        'absent': trends['absent'],
        'rate': trends['rate'],
        'checkin_days': days,
        'checkin_minutes': checkins,
    }


def _check_in(request, employee, today):
    if not employee.is_active:
        messages.error(request, 'Your employee record is inactive.')
        return
    if today.weekday() == 6:
        messages.error(request, 'Today is Sunday, the weekly holiday.')
        return
    if DailyAttendance.objects.filter(employee=employee, date=today).exists():
        messages.info(request, 'Your attendance for today is already recorded.')
        return
    now = timezone.localtime()
    _, created = DailyAttendance.objects.get_or_create(
        employee=employee,
        date=today,
        defaults={'status': 'present', 'check_in_time': now.time().replace(tzinfo=None)},
    )
    if created:
        LeaveRequest.objects.filter(
            employee=employee, date=today, status='pending'
        ).update(
            status='cancelled',
            decided_at=timezone.now(),
            decided_by=request.user.username,
            decision_note='Employee checked in',
        )
        messages.success(request, f"Checked in at {now.strftime('%I:%M %p').lstrip('0')}.")


@login_required
@require_http_methods(['GET', 'POST'])
def portal_dashboard(request):
    employee = _employee(request)
    if employee is None:
        return render(request, 'attendance/portal_dashboard.html', {'employee': None})
    today = timezone.localdate()
    if request.method == 'POST':
        _check_in(request, employee, today)
        return redirect('portal_dashboard')
    year, month = today.year, today.month
    summary = analytics.attendance_summary(employee, year, month)
    trends = _trends(employee, year, month)
    enrollments = StudentEnrollment.objects.filter(counselor=employee)
    payrolls = Payroll.objects.filter(employee=employee)
    current_pay = compute_payroll(employee, year, month)
    avg_incentives = enrollments.filter(
        confirmed_on__year=year, confirmed_on__month=month
    ).aggregate(total=Sum('incentive_amount'))['total'] or Decimal('0.00')
    charts = {
        'months': trends['months'],
        'enrollments': trends['enrollments'],
        'rate': trends['rate'],
    }
    return render(request, 'attendance/portal_dashboard.html', {
        'employee': employee,
        'today': today,
        'today_record': DailyAttendance.objects.filter(employee=employee, date=today).first(),
        'is_sunday': today.weekday() == 6,
        'on_leave': Leave.objects.filter(employee=employee, date=today).exists(),
        'summary': summary,
        'month_enrollments': enrollments.filter(
            confirmed_on__year=year, confirmed_on__month=month
        ).count(),
        'month_incentives': avg_incentives,
        'all_time_incentives': enrollments.aggregate(total=Sum('incentive_amount'))['total'] or Decimal('0.00'),
        'total_earned': payrolls.aggregate(total=Sum('net_pay'))['total'] or Decimal('0.00'),
        'running_estimate': current_pay.net_pay,
        'latest_enrollments': enrollments.order_by('-confirmed_on')[:5],
        'latest_leave_requests': employee.leave_requests.all()[:5],
        'charts': charts,
    })


@login_required
@require_http_methods(['GET', 'POST'])
def portal_attendance(request):
    employee = _employee(request)
    if employee is None:
        return render(request, 'attendance/portal_attendance.html', {'employee': None})
    today = timezone.localdate()
    if request.method == 'POST':
        _check_in(request, employee, today)
        return redirect(request.get_full_path())

    year, month = _period(request)
    return render(request, 'attendance/portal_attendance.html', {
        'employee': employee,
        'today': today,
        'today_record': DailyAttendance.objects.filter(employee=employee, date=today).first(),
        'is_sunday': today.weekday() == 6,
        'year': year,
        'month': month,
        'period_label': analytics.month_label(year, month),
        'options': analytics.month_options(),
        'summary': analytics.attendance_summary(employee, year, month),
        'attendance_log': analytics.attendance_log(employee, year, month),
        'charts': _attendance_charts(employee, year, month),
    })


@login_required
@require_http_methods(['GET', 'POST'])
def portal_leaves(request):
    employee = _employee(request)
    if employee is None:
        return render(request, 'attendance/portal_leaves.html', {'employee': None})
    form = LeaveRequestForm(request.POST or None, employee=employee)
    if request.method == 'POST' and form.is_valid():
        try:
            with transaction.atomic():
                LeaveRequest.objects.create(
                    employee=employee,
                    date=form.cleaned_data['date'],
                    reason=form.cleaned_data['reason'],
                )
            messages.success(request, 'Leave request sent. You will see the decision here once your admin reviews it.')
            return redirect('portal_leaves')
        except IntegrityError:
            form.add_error('date', 'You already have a pending request for that date.')
    today = timezone.localdate()
    leave_requests = employee.leave_requests.all()
    return render(request, 'attendance/portal_leaves.html', {
        'employee': employee,
        'form': form,
        'leave_requests': leave_requests,
        'leaves_this_month': Leave.objects.filter(employee=employee, date__year=today.year, date__month=today.month).count(),
        'upcoming_leave': Leave.objects.filter(employee=employee, date__gte=today).order_by('date'),
        'past_leave': Leave.objects.filter(employee=employee, date__lt=today).order_by('-date'),
    })


@login_required
@require_POST
def leave_request_cancel(request, pk):
    employee = _employee(request)
    leave_request = get_object_or_404(
        LeaveRequest, pk=pk, employee=employee, status='pending'
    )
    leave_request.status = 'cancelled'
    leave_request.decided_at = timezone.now()
    leave_request.decided_by = request.user.username
    leave_request.save(update_fields=['status', 'decided_at', 'decided_by'])
    messages.success(request, 'Leave request cancelled.')
    return redirect('portal_leaves')


@login_required
def portal_enrollments(request):
    employee = _employee(request)
    if employee is None:
        return render(request, 'attendance/portal_enrollments.html', {'employee': None})
    year, month = _period(request)
    all_enrollments = StudentEnrollment.objects.filter(counselor=employee)
    month_enrollments = all_enrollments.filter(
        confirmed_on__year=year, confirmed_on__month=month
    ).order_by('-confirmed_on')
    trends = _trends(employee, year, month)
    countries, country_counts = analytics.country_breakdown(all_enrollments)
    return render(request, 'attendance/portal_enrollments.html', {
        'employee': employee,
        'year': year,
        'month': month,
        'period_label': analytics.month_label(year, month),
        'options': analytics.month_options(),
        'month_enrollments': month_enrollments,
        'all_enrollments': all_enrollments,
        'month_count': month_enrollments.count(),
        'all_count': all_enrollments.count(),
        'month_incentives': month_enrollments.aggregate(total=Sum('incentive_amount'))['total'] or Decimal('0.00'),
        'all_incentives': all_enrollments.aggregate(total=Sum('incentive_amount'))['total'] or Decimal('0.00'),
        'charts': {
            'months': trends['months'],
            'enrollments': trends['enrollments'],
            'incentives': trends['incentives'],
            'countries': countries,
            'country_counts': country_counts,
        },
    })


@login_required
def portal_salary(request):
    employee = _employee(request)
    if employee is None:
        return render(request, 'attendance/portal_salary.html', {'employee': None})
    year, month = _period(request)
    payrolls = Payroll.objects.filter(employee=employee)
    selected_payroll = payrolls.filter(year=year, month=month).first()
    estimate = compute_payroll(employee, year, month)
    this_year = payrolls.filter(year=timezone.localdate().year)
    history = list(payrolls.order_by('-year', '-month'))
    for payroll in history:
        payroll.latest_email_attempt = payroll.email_attempts.first()
    charts = {
        'months': [analytics.month_label(p.year, p.month) for p in reversed(history[:12])],
        'net': [float(p.net_pay) for p in reversed(history[:12])],
        'incentives': [float(p.incentive_total) for p in reversed(history[:12])],
    }
    return render(request, 'attendance/portal_salary.html', {
        'employee': employee,
        'year': year,
        'month': month,
        'period_label': analytics.month_label(year, month),
        'options': analytics.month_options(),
        'payroll': selected_payroll,
        'estimate': estimate,
        'payroll_history': history,
        'total_earned': payrolls.aggregate(total=Sum('net_pay'))['total'] or Decimal('0.00'),
        'year_earned': this_year.aggregate(total=Sum('net_pay'))['total'] or Decimal('0.00'),
        'total_incentives': payrolls.aggregate(total=Sum('incentive_total'))['total'] or Decimal('0.00'),
        'charts': charts,
    })
