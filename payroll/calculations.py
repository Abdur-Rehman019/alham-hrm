import calendar
from decimal import Decimal
from typing import NamedTuple

from django.db.models import Sum

from attendance.models import Leave
from core import analytics
from payroll.models import StudentEnrollment, _whole_rupees


class PayrollCalculation(NamedTuple):
    base_salary: Decimal
    leave_deduction: Decimal
    incentive_total: Decimal
    net_pay: Decimal


def _money(value):
    return _whole_rupees(value)


def compute_payroll(employee, year, month):
    """Return whole-rupee payroll amounts, including leave and absence deductions."""
    leaves_deducted = Leave.objects.filter(
        employee=employee,
        date__year=year,
        date__month=month,
        is_deducted=True,
    ).count()
    absences = analytics.attendance_summary(employee, year, month)['absent']
    days_in_month = calendar.monthrange(year, month)[1]
    per_day_salary = Decimal(employee.monthly_salary) / Decimal(days_in_month)
    deduction = _money(per_day_salary * (leaves_deducted + absences))
    incentives = StudentEnrollment.objects.filter(
        counselor=employee,
        confirmed_on__year=year,
        confirmed_on__month=month,
    ).aggregate(total=Sum('incentive_amount'))['total'] or Decimal('0')
    base = _money(employee.monthly_salary)
    incentive_total = _money(incentives)
    return PayrollCalculation(
        base_salary=base,
        leave_deduction=deduction,
        incentive_total=incentive_total,
        net_pay=_money(base - deduction + incentive_total),
    )
