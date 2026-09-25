from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import Leave, DailyAttendance
from .forms import LeaveForm


@login_required
def leave_list(request):
    leaves = Leave.objects.select_related('employee').all()
    employee_id = request.GET.get('employee', '')
    if employee_id:
        leaves = leaves.filter(employee_id=employee_id)
    from employees.models import Employee
    employees = Employee.objects.filter(is_active=True)
    return render(request, 'attendance/leave_list.html', {
        'leaves': leaves,
        'employees': employees,
        'selected_employee': employee_id,
    })


@login_required
def leave_add(request):
    if request.method == 'POST':
        form = LeaveForm(request.POST)
        if form.is_valid():
            leave = form.save(commit=False)
            try:
                leave.full_clean()
                leave.save()
                if leave.is_deducted:
                    messages.warning(request, f"Leave recorded, this is beyond the 2 free leaves for {leave.employee.name} this month and will be deducted from salary.")
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
def leave_delete(request, pk):
    leave = get_object_or_404(Leave, pk=pk)
    leave.delete()
    messages.success(request, 'Leave entry removed.')
    return redirect('leave_list')


@login_required
def self_attendance(request):
    """Self-service check-in page for a logged-in employee account."""
    employee = getattr(request.user, 'employee_profile', None)
    if employee is None:
        messages.error(request, "Your account isn't linked to an employee record. Contact your admin.")
        return render(request, 'attendance/self_attendance.html', {'employee': None})

    today = timezone.now().date()
    today_record = DailyAttendance.objects.filter(employee=employee, date=today).first()

    if request.method == 'POST' and today_record is None:
        action = request.POST.get('action')
        now = timezone.now()
        if action == 'check_in':
            DailyAttendance.objects.create(
                employee=employee, date=today, status='present',
                check_in_time=now.time(), imported=False,
            )
            messages.success(request, f"Checked in at {now.strftime('%I:%M %p')}.")
        elif action == 'mark_leave':
            Leave.objects.get_or_create(
                employee=employee, date=today,
                defaults={'leave_type': 'casual', 'reason': 'Self-marked'}
            )
            DailyAttendance.objects.create(employee=employee, date=today, status='leave', imported=False)
            messages.success(request, "Today marked as leave.")
        return redirect('self_attendance')

    recent_history = DailyAttendance.objects.filter(employee=employee).order_by('-date')[:10]

    return render(request, 'attendance/self_attendance.html', {
        'employee': employee,
        'today_record': today_record,
        'recent_history': recent_history,
    })