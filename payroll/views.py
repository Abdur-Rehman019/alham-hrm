import calendar
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.core.mail import EmailMessage
from django.db.models import Sum
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.middleware import is_admin_user
from employees.models import Employee
from .calculations import compute_payroll
from .models import IncentiveRule, StudentEnrollment, Payroll, PayslipEmail
from .forms import IncentiveRuleForm, StudentEnrollmentForm

logger = logging.getLogger(__name__)
admin_required = user_passes_test(is_admin_user, login_url='login')


@login_required
@admin_required
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
@admin_required
@require_POST
def incentive_rule_delete(request, pk):
    rule = get_object_or_404(IncentiveRule, pk=pk)
    name = rule.destination_country
    rule.delete()
    messages.success(request, f'Incentive rule for {name} removed.')
    return redirect('incentive_rule_list')

@login_required
@admin_required
def enrollment_list(request):
    enrollments = StudentEnrollment.objects.select_related('counselor').all()
    return render(request, 'payroll/enrollment_list.html', {'enrollments': enrollments})


@login_required
@admin_required
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
    calculation = compute_payroll(employee, year, month)

    payroll, created = Payroll.objects.get_or_create(
        employee=employee, month=month, year=year,
        defaults={
            'base_salary': calculation.base_salary,
            'leave_deduction': calculation.leave_deduction,
            'incentive_total': calculation.incentive_total,
        }
    )
    if not created:
        amounts_changed = (
            payroll.base_salary != calculation.base_salary
            or payroll.leave_deduction != calculation.leave_deduction
            or payroll.incentive_total != calculation.incentive_total
        )
        payroll.base_salary = calculation.base_salary
        payroll.leave_deduction = calculation.leave_deduction
        payroll.incentive_total = calculation.incentive_total
        if amounts_changed:
            payroll.is_approved = False
            payroll.approved_at = None
            payroll.approved_by = None
        payroll.save()
    return payroll, created


@login_required
@admin_required
def payroll_generate(request):
    employees = Employee.objects.filter(is_active=True)
    today = timezone.localdate()
    try:
        selected_month = int(request.GET.get('month', today.month))
        selected_year = int(request.GET.get('year', today.year))
        if not 1 <= selected_month <= 12 or selected_year < 2015 or (selected_year, selected_month) > (today.year, today.month):
            raise ValueError
    except (TypeError, ValueError):
        selected_month, selected_year = today.month, today.year

    if request.method == 'POST':
        try:
            month, year = int(request.POST.get('month')), int(request.POST.get('year'))
            if not 1 <= month <= 12 or year < 2015 or (year, month) > (today.year, today.month):
                raise ValueError
        except (TypeError, ValueError):
            messages.error(request, 'Choose a valid payroll month and year.')
            return redirect('payroll_generate')

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

    payrolls = list(Payroll.objects.filter(
        month=selected_month, year=selected_year
    ).select_related('employee', 'employee__user'))
    for payroll in payrolls:
        current = compute_payroll(payroll.employee, selected_year, selected_month)
        payroll.is_outdated = (
            payroll.base_salary != current.base_salary
            or payroll.leave_deduction != current.leave_deduction
            or payroll.incentive_total != current.incentive_total
        )
        payroll.latest_attempt = payroll.email_attempts.first()
        payroll.email_status = (
            'Outdated' if payroll.is_outdated else
            f"Sent on {timezone.localtime(payroll.latest_attempt.sent_at):%d %b %Y} to {payroll.latest_attempt.recipient}"
            if payroll.latest_attempt and payroll.latest_attempt.success else
            'Approved; delivery failed' if payroll.is_approved and payroll.latest_attempt else
            'Approved; not sent' if payroll.is_approved else
            'Pending approval'
        )
    return render(request, 'payroll/payroll_generate.html', {
        'employees': employees,
        'payrolls': payrolls,
        'selected_month': selected_month,
        'selected_year': selected_year,
        'months': list(calendar.month_name)[1:],
        'period_label': f"{calendar.month_name[selected_month]} {selected_year}",
    })


def _send_payslip(payroll, user):
    recipient = (payroll.employee.user.email if payroll.employee.user_id else '') or payroll.employee.email or ''
    attempt = PayslipEmail.objects.create(
        payroll=payroll,
        recipient=recipient,
        sent_by=user,
    )
    if not payroll.is_approved:
        attempt.error = 'Payroll must be approved before emailing a payslip.'
        attempt.save(update_fields=['error'])
        return False, 'payroll has not been approved'
    calculation = compute_payroll(payroll.employee, payroll.year, payroll.month)
    if (
        payroll.base_salary != calculation.base_salary
        or payroll.leave_deduction != calculation.leave_deduction
        or payroll.incentive_total != calculation.incentive_total
    ):
        attempt.error = 'Payroll is outdated; regenerate it before sending.'
        attempt.save(update_fields=['error'])
        return False, 'outdated payroll'
    if not recipient:
        attempt.error = 'No email address is configured for this employee.'
        attempt.save(update_fields=['error'])
        return False, 'no email address'

    try:
        pdf = _payslip_pdf_response(payroll).content
        message = EmailMessage(
            subject=f"Your payslip for {calendar.month_name[payroll.month]} {payroll.year}",
            body=(
                f"Hello {payroll.employee.name},\n\n"
                f"Here is your payslip for {calendar.month_name[payroll.month]} {payroll.year}.\n"
                f"Base salary: PKR {payroll.base_salary:,.2f}\n"
                f"Leave and absence deduction: PKR {payroll.leave_deduction:,.2f}\n"
                f"Incentives: PKR {payroll.incentive_total:,.2f}\n"
                f"Net pay: PKR {payroll.net_pay:,.2f}\n"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[recipient],
        )
        message.attach(
            f"Payslip_{payroll.employee.employee_id}_{payroll.year}_{payroll.month:02d}.pdf",
            pdf,
            'application/pdf',
        )
        if message.send(fail_silently=False) != 1:
            raise RuntimeError('Email backend did not send the message.')
    except Exception as exc:
        logger.exception('Payslip email failed for payroll %s', payroll.pk)
        attempt.error = str(exc)[:2000]
        attempt.save(update_fields=['error'])
        return False, 'email delivery failed'

    attempt.success = True
    attempt.save(update_fields=['success'])
    return True, recipient


@login_required
@admin_required
@require_POST
def payroll_approve(request, pk):
    payroll = get_object_or_404(
        Payroll.objects.select_related('employee', 'employee__user'), pk=pk
    )
    calculation = compute_payroll(payroll.employee, payroll.year, payroll.month)
    if (
        payroll.base_salary != calculation.base_salary
        or payroll.leave_deduction != calculation.leave_deduction
        or payroll.incentive_total != calculation.incentive_total
    ):
        messages.error(request, f"{payroll.employee.name}: payroll is outdated. Regenerate it before approval.")
        return redirect(f"/payroll/generate/?month={payroll.month}&year={payroll.year}")
    if payroll.is_approved:
        messages.info(request, f"{payroll.employee.name}'s payroll is already approved. Use resend if delivery needs retrying.")
        return redirect(f"/payroll/generate/?month={payroll.month}&year={payroll.year}")

    payroll.is_approved = True
    payroll.approved_at = timezone.now()
    payroll.approved_by = request.user
    payroll.save(update_fields=['is_approved', 'approved_at', 'approved_by', 'net_pay'])
    success, result = _send_payslip(payroll, request.user)
    if success:
        messages.success(request, f"Payroll approved and payslip sent to {result}.")
    else:
        messages.warning(request, f"{payroll.employee.name}'s payroll is approved, but the payslip was not sent ({result}). Correct the issue, then use Resend.")
    return redirect(f"/payroll/generate/?month={payroll.month}&year={payroll.year}")


@login_required
@admin_required
@require_POST
def payslip_email_send(request, pk):
    payroll = get_object_or_404(Payroll.objects.select_related('employee', 'employee__user'), pk=pk)
    success, result = _send_payslip(payroll, request.user)
    if success:
        messages.success(request, f"Payslip resent to {result}.")
    else:
        messages.error(request, f"{payroll.employee.name}: {result}. Approval is required before a payslip can be sent.")
    return redirect(f"/payroll/generate/?month={payroll.month}&year={payroll.year}")


@login_required
@admin_required
def payslip_pdf(request, pk):
    payroll = get_object_or_404(Payroll, pk=pk)
    return _payslip_pdf_response(payroll)


def _payslip_pdf_response(payroll):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor
    from reportlab.pdfgen import canvas as pdf_canvas

    employee = payroll.employee

    response = HttpResponse(content_type='application/pdf')
    filename = f"Payslip_{employee.employee_id}_{payroll.year}_{payroll.month:02d}.pdf"
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
        ("Leave and Absence Deduction", f"- PKR {payroll.leave_deduction:,.2f}", HexColor('#dc2626')),
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