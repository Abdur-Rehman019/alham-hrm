from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.views.decorators.http import require_POST
from .models import Employee
from .forms import EmployeeForm
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
@require_POST
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
        leaving_date = request.POST.get('leaving_date') or timezone.localdate().isoformat()
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
@require_POST
def employee_remove_login(request, pk):
    employee = get_object_or_404(Employee, pk=pk)
    user = employee.user
    if user and (user.is_staff or user.is_superuser):
        messages.error(request, "This login belongs to an administrator; remove it from Django Admin instead.")
    elif user:
        # Deleting the user clears Employee.user (SET_NULL) without re-validating older employee records.
        user.delete()
        Employee.objects.filter(pk=employee.pk).update(must_change_password=False)
        messages.success(request, f"Login access removed for {employee.name}.")
    return redirect('employee_detail', pk=employee.pk)