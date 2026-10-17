import calendar
import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core import analytics
from core.middleware import is_admin_user
from employees.models import Employee
from .forms import LeaveForm
from .models import FREE_LEAVES_PER_MONTH, DailyAttendance, Leave, LeaveRequest

admin_required = user_passes_test(is_admin_user, login_url='login')
MAX_LEAVE_ADVANCE_DAYS = 60


def _recompute_leave_flags(employee, year, month):
    """Free leaves are the first N of the month; re-assign after one is removed."""
    leaves = Leave.objects.filter(employee=employee, date__year=year, date__month=month).order_by('created_at', 'id')
    for index, leave in enumerate(leaves):
        should = index >= FREE_LEAVES_PER_MONTH
        if leave.is_deducted != should:
            Leave.objects.filter(pk=leave.pk).update(is_deducted=should)


# ----------------------------------------------------------------- admin: leave records
@login_required
@admin_required
def leave_list(request):
    leaves = Leave.objects.select_related('employee').all()
    employee_id = request.GET.get('employee', '')
    if employee_id.isdigit():
        leaves = leaves.filter(employee_id=employee_id)
    return render(request, 'attendance/leave_list.html', {
        'leaves': leaves,
        'employees': Employee.objects.filter(is_active=True),
        'selected_employee': employee_id,
    })


@login_required
@admin_required
def leave_add(request):
    if request.method == 'POST':
        form = LeaveForm(request.POST)
        if form.is_valid():
            leave = form.save(commit=False)
            try:
                leave.full_clean()
                with transaction.atomic():
                    leave.save()
                    DailyAttendance.objects.update_or_create(
                        employee=leave.employee, date=leave.date,
                        defaults={'status': 'leave', 'check_in_time': None, 'is_late': False, 'imported': False},
                    )
                if leave.is_deducted:
                    messages.warning(request, f"Leave recorded. This is beyond the {FREE_LEAVES_PER_MONTH} free leaves for {leave.employee.name} this month, so it will be deducted from salary.")
                else:
                    messages.success(request, 'Leave recorded successfully.')
                return redirect('leave_list')
            except ValidationError as e:
                for field, errs in e.message_dict.items():
                    for err in errs:
                        form.add_error(field if field in form.fields else None, err)
    else:
        form = LeaveForm()
    return render(request, 'attendance/leave_form.html', {'form': form})


@login_required
@admin_required
@require_POST
def leave_delete(request, pk):
    leave = get_object_or_404(Leave, pk=pk)
    employee, date = leave.employee, leave.date
    with transaction.atomic():
        leave.delete()
        DailyAttendance.objects.filter(employee=employee, date=date, status='leave').delete()
        _recompute_leave_flags(employee, date.year, date.month)
    messages.success(request, 'Leave entry removed.')
    return redirect('leave_list')


@login_required
@admin_required
@require_POST
def holiday_add(request):
    """Mark a public holiday for every active employee so nobody is counted absent that day."""
    try:
        day = datetime.date.fromisoformat(request.POST.get('date', ''))
    except ValueError:
        messages.error(request, "Please choose a valid date.")
        return redirect('leave_list')
    name = request.POST.get('name', '').strip()[:100] or 'Public holiday'
    added = 0
    with transaction.atomic():
        for emp in Employee.objects.filter(is_active=True, joined_on__lte=day):
            # anyone who already has a record that day (e.g. they came in) is left untouched
            _, made = DailyAttendance.objects.get_or_create(
                employee=emp, date=day,
                defaults={'status': 'holiday', 'note': name, 'imported': False})
            added += made
    messages.success(request, f"{name} ({day:%d %b %Y}) marked for {added} employee{'s' if added != 1 else ''}.")
    return redirect('leave_list')


# ---------------------------------------------------------------- admin: leave requests
@login_required
@admin_required
def leave_requests_list(request):
    pending = list(LeaveRequest.objects.select_related('employee').filter(status='pending').order_by('date'))
    for r in pending:
        used = Leave.objects.filter(employee=r.employee, date__year=r.date.year, date__month=r.date.month).count()
        r.leaves_used = used
        r.will_deduct = used >= FREE_LEAVES_PER_MONTH
    recent = LeaveRequest.objects.select_related('employee').exclude(status='pending')[:15]
    return render(request, 'attendance/leave_requests.html', {
        'pending': pending, 'recent': recent, 'free_leaves': FREE_LEAVES_PER_MONTH,
    })


@login_required
@admin_required
@require_POST
def leave_request_approve(request, pk):
    lr = get_object_or_404(LeaveRequest.objects.select_related('employee'), pk=pk)
    if lr.status != 'pending':
        messages.info(request, 'That request was already handled.')
        return redirect('leave_requests_list')
    existing = DailyAttendance.objects.filter(employee=lr.employee, date=lr.date).first()
    if existing and existing.status == 'present':
        messages.error(request, f"{lr.employee.name} already checked in on {lr.date}. Reject this request, or correct the attendance first.")
        return redirect('leave_requests_list')

    with transaction.atomic():
        updated = LeaveRequest.objects.filter(pk=lr.pk, status='pending').update(
            status='approved', decided_at=timezone.now(), decided_by=request.user.username)
        if not updated:  # another admin got there first
            return redirect('leave_requests_list')
        Leave.objects.get_or_create(
            employee=lr.employee, date=lr.date,
            defaults={'leave_type': 'casual', 'reason': lr.reason or 'Approved leave request'},
        )
        DailyAttendance.objects.update_or_create(
            employee=lr.employee, date=lr.date,
            defaults={'status': 'leave', 'check_in_time': None, 'is_late': False, 'imported': False},
        )
    messages.success(request, f"Leave approved for {lr.employee.name} on {lr.date}.")
    return redirect('leave_requests_list')


@login_required
@admin_required
@require_POST
def leave_request_reject(request, pk):
    lr = get_object_or_404(LeaveRequest.objects.select_related('employee'), pk=pk)
    note = request.POST.get('note', '').strip()[:255]
    updated = LeaveRequest.objects.filter(pk=lr.pk, status='pending').update(
        status='rejected', decided_at=timezone.now(), decided_by=request.user.username, decision_note=note)
    if updated:
        messages.success(request, f"Leave request rejected for {lr.employee.name}.")
    else:
        messages.info(request, 'That request was already handled.')
    return redirect('leave_requests_list')


# ------------------------------------------------------------------ employee portal
def _portal_post(request, employee, today):
    action = request.POST.get('action')
    if not employee.is_active:
        messages.error(request, "Your employee record is inactive.")
        return

    if action == 'check_in':
        if today.weekday() == 6:
            messages.error(request, "Today is Sunday, the weekly holiday.")
            return
        if DailyAttendance.objects.filter(employee=employee, date=today).exists():
            messages.info(request, "Your attendance for today is already recorded.")
            return
        now = timezone.localtime()
        _, created = DailyAttendance.objects.get_or_create(
            employee=employee, date=today,
            defaults={'status': 'present', 'check_in_time': now.time().replace(microsecond=0), 'imported': False},
        )
        if created:
            LeaveRequest.objects.filter(employee=employee, date=today, status='pending').update(
                status='cancelled', decision_note='Employee checked in')
            messages.success(request, f"Checked in at {now.strftime('%I:%M %p').lstrip('0')}.")

    elif action == 'request_leave':
        try:
            day = datetime.date.fromisoformat(request.POST.get('leave_date', ''))
        except ValueError:
            messages.error(request, "Please choose a valid date.")
            return
        reason = request.POST.get('reason', '').strip()[:255]
        if len(reason) < 3:
            messages.error(request, "Please give a short reason for the leave.")
        elif day < today:
            messages.error(request, "You cannot request leave for a past date.")
        elif day > today + datetime.timedelta(days=MAX_LEAVE_ADVANCE_DAYS):
            messages.error(request, f"Leave can be requested up to {MAX_LEAVE_ADVANCE_DAYS} days ahead.")
        elif day.weekday() == 6:
            messages.error(request, "Sunday is already a holiday.")
        elif day < employee.joined_on:
            messages.error(request, "That date is before your joining date.")
        elif Leave.objects.filter(employee=employee, date=day).exists() or \
                DailyAttendance.objects.filter(employee=employee, date=day, status='leave').exists():
            messages.error(request, "You already have approved leave on that date.")
        elif day == today and DailyAttendance.objects.filter(employee=employee, date=day).exists():
            messages.error(request, "Your attendance for today is already recorded.")
        else:
            try:
                with transaction.atomic():
                    LeaveRequest.objects.create(employee=employee, date=day, reason=reason)
                messages.success(request, "Leave request sent. You will see the decision here once your admin reviews it.")
            except IntegrityError:
                messages.error(request, "You already have a pending request for that date.")


@login_required
def self_attendance(request):
    employee = getattr(request.user, 'employee_profile', None)
    if employee is None:
        return render(request, 'attendance/self_attendance.html', {'employee': None})
    today = timezone.localdate()

    if request.method == 'POST':
        _portal_post(request, employee, today)
        return redirect(request.get_full_path())

    from payroll.models import Payroll, StudentEnrollment
    year, month = analytics.parse_period(request)
    today_record = DailyAttendance.objects.filter(employee=employee, date=today).first()
    summary = analytics.attendance_summary(employee, year, month)
    trends = analytics.employee_trends(employee, year, month)

    leaves = Leave.objects.filter(employee=employee, date__year=year, date__month=month).order_by('date')
    deducted = leaves.filter(is_deducted=True).count()
    days_in_month = calendar.monthrange(year, month)[1]
    est_deduction = round(float(employee.monthly_salary) / days_in_month * deducted, 2)

    month_enrollments = StudentEnrollment.objects.filter(
        counselor=employee, confirmed_on__year=year, confirmed_on__month=month).order_by('-confirmed_on')
    month_incentive = month_enrollments.aggregate(t=Sum('incentive_amount'))['t'] or 0
    all_enrollments = StudentEnrollment.objects.filter(counselor=employee)
    countries, country_counts = analytics.country_breakdown(all_enrollments)
    payrolls = list(Payroll.objects.filter(employee=employee)[:6])
    payroll_for_month = Payroll.objects.filter(employee=employee, year=year, month=month).first()

    return render(request, 'attendance/self_attendance.html', {
        'employee': employee, 'today': today, 'today_record': today_record,
        'is_sunday': today.weekday() == 6,
        'year': year, 'month': month,
        'period_label': f"{calendar.month_name[month]} {year}",
        'options': analytics.month_options(),
        'summary': summary, 'leaves': leaves, 'free_leaves': FREE_LEAVES_PER_MONTH, 'leaves_deducted': deducted,
        'est_deduction': est_deduction,
        'est_net': round(float(employee.monthly_salary) - est_deduction + float(month_incentive), 2),
        'month_enrollments': month_enrollments, 'month_incentive': month_incentive,
        'all_time_count': all_enrollments.count(),
        'all_time_incentive': all_enrollments.aggregate(t=Sum('incentive_amount'))['t'] or 0,
        'payroll_for_month': payroll_for_month, 'payrolls': payrolls,
        'recent_history': analytics.attendance_log(employee, year, month)[:12],
        'leave_requests': LeaveRequest.objects.filter(employee=employee)[:10],
        'leave_min': today.isoformat(),
        'leave_max': (today + datetime.timedelta(days=MAX_LEAVE_ADVANCE_DAYS)).isoformat(),
        'charts': {**trends, 'countries': countries, 'country_counts': country_counts},
        'has_enrollments': any(trends['enrollments']), 'has_attendance': any(trends['present']) or any(trends['leave']) or any(trends['absent']),
        'has_countries': bool(countries),
    })


@login_required
@require_POST
def leave_request_cancel(request, pk):
    employee = getattr(request.user, 'employee_profile', None)
    lr = get_object_or_404(LeaveRequest, pk=pk, employee=employee, status='pending')
    lr.status = 'cancelled'
    lr.decided_at = timezone.now()
    lr.decided_by = request.user.username
    lr.save()
    messages.success(request, 'Leave request cancelled.')
    return redirect('self_attendance')


@login_required
def my_payslip_pdf(request, pk):
    """An employee can download only their own payslip."""
    from payroll.models import Payroll
    from payroll.views import payslip_pdf
    employee = getattr(request.user, 'employee_profile', None)
    get_object_or_404(Payroll, pk=pk, employee=employee)
    return payslip_pdf(request, pk)