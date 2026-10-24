import calendar

from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from core.middleware import is_admin_user
from employees.models import Employee
from payroll.models import StudentEnrollment

from .certificate import draw_counselor_certificate


@login_required
@user_passes_test(is_admin_user, login_url='login')
def counselor_of_month_certificate(request, employee_id, year, month):
    if not 1 <= month <= 12:
        return HttpResponse(status=404)
    employee = get_object_or_404(Employee, pk=employee_id)
    period_label = f"{calendar.month_name[month]} {year}"
    enrollment_count = StudentEnrollment.objects.filter(
        counselor=employee,
        confirmed_on__year=year,
        confirmed_on__month=month,
    ).count()
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = (
        f'attachment; filename="Certificate_{employee.employee_id}_{month}_{year}.pdf"'
    )
    # Demo employees are named "Demo - Hina Malik"; the certificate shows the person's name only.
    name = employee.name.split(' - ', 1)[1] if employee.name.startswith('Demo - ') else employee.name
    draw_counselor_certificate(response, name, period_label, enrollment_count)
    return response
