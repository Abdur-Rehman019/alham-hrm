from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.db.models import Sum
from django.http import HttpResponse
import calendar
from .models import IncentiveRule, StudentEnrollment, Payroll
from .forms import IncentiveRuleForm, StudentEnrollmentForm
from employees.models import Employee
from attendance.models import Leave


@login_required
def incentive_rule_list(request):
    rules = IncentiveRule.objects.all().order_by('destination_country')
    edit_id = request.GET.get('edit')
    instance = IncentiveRule.objects.filter(pk=edit_id).first() if edit_id else None

    if request.method == 'POST':
        rule_id = request.POST.get('rule_id')
        instance = IncentiveRule.objects.filter(pk=rule_id).first() if rule_id else None
        form = IncentiveRuleForm(request.POST, instance=instance)
        if form.is_valid():
            try:
                rule = form.save(commit=False)
                rule.full_clean()
                rule.save()
                messages.success(request, 'Incentive rule saved.')
                return redirect('incentive_rule_list')
            except ValidationError as e:
                for field, errs in e.message_dict.items():
                    for err in errs:
                        form.add_error(field if field in form.fields else None, err)
    else:
        form = IncentiveRuleForm(instance=instance)
    return render(request, 'payroll/incentive_rule_list.html', {
        'rules': rules, 'form': form, 'editing': instance,
    })


@login_required
def incentive_rule_delete(request, pk):
    rule = get_object_or_404(IncentiveRule, pk=pk)
    name = rule.destination_country
    rule.delete()
    messages.success(request, f'Incentive rule for {name} removed.')
    return redirect('incentive_rule_list')

@login_required
def enrollment_list(request):
    enrollments = StudentEnrollment.objects.select_related('counselor').all()
    return render(request, 'payroll/enrollment_list.html', {'enrollments': enrollments})


@login_required
def enrollment_add(request):
    if request.method == 'POST':
        form = StudentEnrollmentForm(request.POST)
        if form.is_valid():
            try:
                enrollment = form.save(commit=False)
                enrollment.full_clean()
                enrollment.save()
                messages.success(request, f"Enrollment recorded. Incentive of PKR {enrollment.incentive_amount} assigned to {enrollment.counselor.name}.")
                return redirect('enrollment_list')
            except ValidationError as e:
                for field, errs in e.message_dict.items():
                    for err in errs:
                        form.add_error(field if field in form.fields else None, err)
    else:
        form = StudentEnrollmentForm()
    countries = IncentiveRule.objects.values_list('destination_country', flat=True)
    return render(request, 'payroll/enrollment_form.html', {'form': form, 'countries': countries})


def _calculate_and_save_payroll(employee, year, month):
    deducted_leaves = Leave.objects.filter(
        employee=employee, date__year=year, date__month=month, is_deducted=True
    ).count()
    days_in_month = calendar.monthrange(year, month)[1]
    per_day_rate = employee.monthly_salary / days_in_month
    leave_deduction = round(per_day_rate * deducted_leaves, 2)

    incentive_total = StudentEnrollment.objects.filter(
        counselor=employee, confirmed_on__year=year, confirmed_on__month=month
    ).aggregate(total=Sum('incentive_amount'))['total'] or 0

    payroll, created = Payroll.objects.get_or_create(
        employee=employee, month=month, year=year,
        defaults={
            'base_salary': employee.monthly_salary,
            'leave_deduction': leave_deduction,
            'incentive_total': incentive_total,
        }
    )
    if not created:
        payroll.base_salary = employee.monthly_salary
        payroll.leave_deduction = leave_deduction
        payroll.incentive_total = incentive_total
        payroll.save()
    return payroll, created


@login_required
def payroll_generate(request):
    employees = Employee.objects.filter(is_active=True)
    today = timezone.now().date()
    selected_month = int(request.GET.get('month', today.month))
    selected_year = int(request.GET.get('year', today.year))

    if request.method == 'POST':
        month = int(request.POST.get('month'))
        year = int(request.POST.get('year'))

        if request.POST.get('generate_all'):
            generated, updated = 0, 0
            for employee in Employee.objects.filter(is_active=True):
                payroll, created = _calculate_and_save_payroll(employee, year, month)
                if created:
                    generated += 1
                else:
                    updated += 1
            messages.success(
                request,
                f"Payroll processed for all active employees: {generated} generated, {updated} updated."
            )
        else:
            employee_id = request.POST.get('employee_id')
            employee = get_object_or_404(Employee, pk=employee_id)
            payroll, created = _calculate_and_save_payroll(employee, year, month)
            messages.success(request, f"Payroll {'generated' if created else 'updated'} for {employee.name}, net pay PKR {payroll.net_pay}.")

        return redirect(f"{request.path}?month={month}&year={year}")

    payrolls = Payroll.objects.filter(month=selected_month, year=selected_year).select_related('employee')
    return render(request, 'payroll/payroll_generate.html', {
        'employees': employees,
        'payrolls': payrolls,
        'selected_month': selected_month,
        'selected_year': selected_year,
        'months': list(calendar.month_name)[1:],
    })


@login_required
def payslip_pdf(request, pk):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor
    from reportlab.pdfgen import canvas as pdf_canvas

    payroll = get_object_or_404(Payroll, pk=pk)
    employee = payroll.employee

    response = HttpResponse(content_type='application/pdf')
    filename = f"Payslip_{employee.employee_id}_{payroll.month}_{payroll.year}.pdf"
    response['Content-Disposition'] = f'attachment; filename="{filename}"'

    PRIMARY = HexColor('#063fb0')
    DARK = HexColor('#111827')
    GRAY = HexColor('#6b7280')

    c = pdf_canvas.Canvas(response, pagesize=A4)
    width, height = A4
    margin = 20 * mm

    c.setFillColor(PRIMARY)
    c.rect(0, height - 30 * mm, width, 30 * mm, fill=1, stroke=0)
    c.setFillColor(HexColor('#ffffff'))
    c.setFont("Helvetica-Bold", 20)
    c.drawString(margin, height - 18 * mm, "ALHAM OVERSEAS CONSULTANTS")
    c.setFont("Helvetica", 11)
    c.drawString(margin, height - 25 * mm, "Payslip")

    y = height - 45 * mm
    c.setFillColor(DARK)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(margin, y, employee.name)
    c.setFont("Helvetica", 10)
    c.setFillColor(GRAY)
    c.drawString(margin, y - 6 * mm, f"{employee.employee_id}  |  {employee.get_role_display()}")
    c.drawString(margin, y - 12 * mm, f"Pay period: {calendar.month_name[payroll.month]} {payroll.year}")

    y -= 28 * mm
    row_h = 9 * mm
    rows = [
        ("Base Salary", f"PKR {payroll.base_salary:,.2f}", DARK),
        ("Leave Deduction", f"- PKR {payroll.leave_deduction:,.2f}", HexColor('#dc2626')),
        ("Incentives", f"+ PKR {payroll.incentive_total:,.2f}", HexColor('#16a34a')),
    ]
    c.setStrokeColor(HexColor('#e5e7eb'))
    c.line(margin, y + 4 * mm, width - margin, y + 4 * mm)
    for label, value, color in rows:
        c.setFont("Helvetica", 11)
        c.setFillColor(DARK)
        c.drawString(margin, y, label)
        c.setFillColor(color)
        c.drawRightString(width - margin, y, value)
        y -= row_h
    c.setStrokeColor(HexColor('#e5e7eb'))
    c.line(margin, y + 4 * mm, width - margin, y + 4 * mm)

    y -= 4 * mm
    c.setFillColor(PRIMARY)
    c.rect(margin, y - 10 * mm, width - 2 * margin, 12 * mm, fill=1, stroke=0)
    c.setFillColor(HexColor('#ffffff'))
    c.setFont("Helvetica-Bold", 13)
    c.drawString(margin + 4 * mm, y - 6.5 * mm, "Net Pay")
    c.drawRightString(width - margin - 4 * mm, y - 6.5 * mm, f"PKR {payroll.net_pay:,.2f}")

    c.setFont("Helvetica-Oblique", 8)
    c.setFillColor(GRAY)
    c.drawCentredString(width / 2, 15 * mm, "This is a system-generated payslip from ALHAM HRM.")

    c.showPage()
    c.save()
    return response