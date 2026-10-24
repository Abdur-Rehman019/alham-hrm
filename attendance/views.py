import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core import analytics, audit
from core.middleware import client_ip, is_admin_user
from employees.models import Employee
from payroll.models import Payroll
from .forms import AttendanceEditForm, LeaveForm, OfficeLocationForm
from .models import FREE_LEAVES_PER_MONTH, DailyAttendance, Leave, LeaveRequest, OfficeLocation

admin_required = user_passes_test(is_admin_user, login_url='login')


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


@login_required
@admin_required
def attendance_edit(request, employee_pk, day):
    """Correct one day for one employee: wrong check-in time, wrong status, or a day with no record."""
    employee = get_object_or_404(Employee, pk=employee_pk)
    try:
        date = datetime.date.fromisoformat(day)
    except ValueError:
        raise Http404
    back = f"{reverse('employee_detail', args=[employee.pk])}?month={date.month}&year={date.year}"
    if date > timezone.localdate() or date < employee.joined_on or (employee.leaving_date and date > employee.leaving_date):
        messages.error(request, f"{date:%d %b %Y} is outside {employee.name}'s employment, or in the future.")
        return redirect(back)

    record = DailyAttendance.objects.filter(employee=employee, date=date).first()
    initial = {'status': record.status if record and record.status != 'needs_review' else 'present',
               'check_in_time': record.check_in_time if record else None}
    form = AttendanceEditForm(request.POST or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        status, check_in, reason = (form.cleaned_data[k] for k in ('status', 'check_in_time', 'reason'))
        before = {'status': record.status, 'check_in_time': _plain_time(record.check_in_time)} if record else None
        with transaction.atomic():
            record, _ = DailyAttendance.objects.update_or_create(
                employee=employee, date=date,
                defaults={'status': status, 'check_in_time': check_in, 'note': f'Corrected by HR: {reason}'[:100]})
            had_leave = Leave.objects.filter(employee=employee, date=date).exists()
            if status == 'leave' and not had_leave:
                Leave.objects.create(employee=employee, date=date, leave_type='casual', reason=f'Set by HR: {reason}'[:255])
            elif status != 'leave' and had_leave:
                Leave.objects.filter(employee=employee, date=date).delete()
            _recompute_leave_flags(employee, date.year, date.month)
        after = {'status': status, 'check_in_time': _plain_time(check_in)}
        changes = {k: [before[k] if before else None, after[k]] for k in after if not before or before[k] != after[k]}
        audit.record(record, 'update' if before else 'create', changes,
                     note=f'{employee.name}, {date:%d %b %Y}: {reason}', category='attendance')
        messages.success(request, f"{employee.name}'s attendance for {date:%d %b %Y} updated.")
        if Payroll.objects.filter(employee=employee, year=date.year, month=date.month).exists():
            messages.warning(request, f"Payroll for {date:%B %Y} already exists for {employee.name}. "
                                      "Regenerate it on the Payroll page so the change is reflected.")
        return redirect(back)
    return render(request, 'attendance/attendance_edit.html', {
        'form': form, 'employee': employee, 'date': date, 'record': record, 'back': back,
    })


def _plain_time(value):
    return value.strftime('%H:%M') if value else None


@login_required
@admin_required
def office_location(request):
    """Where employees may check in from: office internet IPs and/or a GPS point with a radius."""
    location = OfficeLocation.current() or OfficeLocation()
    current_ip = client_ip(request)
    if request.method == 'POST' and request.POST.get('action') == 'add_my_ip':
        ips = location.ip_list
        if current_ip and current_ip not in ips:
            location.allowed_ips = '\n'.join([*ips, current_ip])
            location.save()
            messages.success(request, f'Added {current_ip}. Check-ins from this internet connection now count as in the office.')
        else:
            messages.info(request, f'{current_ip} is already on the list.')
        return redirect('office_location')

    form = OfficeLocationForm(request.POST or None, instance=location)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Check-in location saved.')
        return redirect('office_location')
    return render(request, 'attendance/office_location.html', {
        'form': form, 'location': location, 'current_ip': current_ip,
        'current_ip_listed': current_ip in location.ip_list,
    })
