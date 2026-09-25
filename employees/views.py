import calendar
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Sum
from django.utils import timezone
import json
from .models import Employee
from .forms import EmployeeForm, CreateLoginForm
from core.middleware import is_admin_user

admin_required = user_passes_test(is_admin_user, login_url='login')


@login_required
@admin_required
def employee_list(request):
    query = request.GET.get('q', '')
    status = request.GET.get('status', 'active')

    employees = Employee.objects.all()
    if query:
        employees = employees.filter(name__icontains=query)
    if status == 'active':
        employees = employees.filter(is_active=True)
    elif status == 'inactive':
        employees = employees.filter(is_active=False)

    return render(request, 'employees/employee_list.html', {
        'employees': employees,
        'query': query,
        'status': status,
    })


@login_required
@admin_required
def employee_detail(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    leaves = employee.leaves.all()[:12]
    enrollments = employee.enrollments.all()[:12]
    payrolls = employee.payrolls.all()[:12]

    payroll_months = [f"{p.month}/{p.year}" for p in reversed(payrolls)]
    payroll_netpay = [float(p.net_pay) for p in reversed(payrolls)]

    today = timezone.now().date()
    enrollment_trend_months = []
    enrollment_trend_counts = []
    attendance_trend_present = []
    attendance_trend_leave = []
    attendance_trend_absent = []
    for i in range(5, -1, -1):
        month = today.month - i
        year = today.year
        while month <= 0:
            month += 12
            year -= 1
        enrollment_trend_months.append(f"{calendar.month_abbr[month]} {year}")
        enrollment_trend_counts.append(
            employee.enrollments.filter(confirmed_on__year=year, confirmed_on__month=month).count()
        )
        month_attendance = employee.daily_attendance.filter(date__year=year, date__month=month)
        attendance_trend_present.append(month_attendance.filter(status='present').count())
        attendance_trend_leave.append(month_attendance.filter(status='leave').count())
        attendance_trend_absent.append(month_attendance.filter(status='absent').count())

    return render(request, 'employees/employee_detail.html', {
        'employee': employee,
        'leaves': leaves,
        'enrollments': enrollments,
        'payrolls': payrolls,
        'payroll_months_json': json.dumps(payroll_months, cls=DjangoJSONEncoder),
        'payroll_netpay_json': json.dumps(payroll_netpay, cls=DjangoJSONEncoder),
        'has_payroll_data': any(payroll_netpay),
        'enrollment_trend_months_json': json.dumps(enrollment_trend_months, cls=DjangoJSONEncoder),
        'enrollment_trend_counts_json': json.dumps(enrollment_trend_counts, cls=DjangoJSONEncoder),
        'has_enrollment_trend_data': any(enrollment_trend_counts),
        'attendance_trend_months_json': json.dumps(enrollment_trend_months, cls=DjangoJSONEncoder),
        'attendance_trend_present_json': json.dumps(attendance_trend_present, cls=DjangoJSONEncoder),
        'attendance_trend_leave_json': json.dumps(attendance_trend_leave, cls=DjangoJSONEncoder),
        'attendance_trend_absent_json': json.dumps(attendance_trend_absent, cls=DjangoJSONEncoder),
        'has_attendance_trend_data': any(attendance_trend_present) or any(attendance_trend_leave) or any(attendance_trend_absent),
    })


@login_required
@admin_required
def employee_add(request):
    if request.method == 'POST':
        form = EmployeeForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                employee = form.save(commit=False)
                employee.full_clean()
                employee.save()
                messages.success(request, 'Employee added successfully.')
                return redirect('employee_list')
            except ValidationError as e:
                for field, errs in e.message_dict.items():
                    for err in errs:
                        form.add_error(field if field in form.fields else None, err)
    else:
        form = EmployeeForm()
    return render(request, 'employees/employee_form.html', {'form': form})


@login_required
@admin_required
def employee_edit(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if request.method == 'POST':
        form = EmployeeForm(request.POST, request.FILES, instance=employee)
        if form.is_valid():
            try:
                emp = form.save(commit=False)
                emp.full_clean()
                emp.save()
                messages.success(request, 'Employee updated successfully.')
                return redirect('employee_list')
            except ValidationError as e:
                for field, errs in e.message_dict.items():
                    for err in errs:
                        form.add_error(field if field in form.fields else None, err)
    else:
        form = EmployeeForm(instance=employee)
    return render(request, 'employees/employee_form.html', {'form': form})


@login_required
@admin_required
def employee_deactivate(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    employee.is_active = False
    employee.save()
    messages.success(request, f"{employee.name} has been deactivated.")
    return redirect('employee_list')


@login_required
@admin_required
def employee_terminate(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if request.method == 'POST':
        leaving_date = request.POST.get('leaving_date') or timezone.now().date().isoformat()
        employee.leaving_date = leaving_date
        employee.is_active = False
        try:
            employee.full_clean()
            employee.save()
            messages.success(request, f"{employee.name} has been terminated, effective {leaving_date}.")
            return redirect('employee_detail', pk=employee.pk)
        except ValidationError as e:
            messages.error(request, ' '.join(str(v) for vs in e.message_dict.values() for v in vs))
    return render(request, 'employees/employee_terminate.html', {'employee': employee})


@login_required
@admin_required
def employee_create_login(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if request.method == 'POST':
        form = CreateLoginForm(request.POST)
        if form.is_valid():
            user = User.objects.create_user(
            username=form.cleaned_data['username'],
            email=form.cleaned_data.get('email', ''),
            password=form.cleaned_data['password1'],
            is_staff=False,
            )
            employee.user = user
            employee.save()
            messages.success(request, f"Login created for {employee.name}. Share the username and password with them securely.")
            return redirect('employee_detail', pk=employee.pk)
    else:
        form = CreateLoginForm()
    return render(request, 'employees/employee_create_login.html', {'form': form, 'employee': employee})


@login_required
@admin_required
def employee_remove_login(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    if employee.user:
        employee.user.delete()
        employee.user = None
        employee.save()
        messages.success(request, f"Login access removed for {employee.name}.")
    return redirect('employee_detail', pk=employee.pk)