from django.contrib.auth.decorators import login_required
from django.shortcuts import render, get_object_or_404
from django.db.models import Sum, Count
from django.utils import timezone
from datetime import date
from django.core.serializers.json import DjangoJSONEncoder
import calendar
import json
from employees.models import Employee
from attendance.models import Leave, DailyAttendance
from payroll.models import StudentEnrollment, Payroll


@login_required
def dashboard_home(request):
    today = timezone.now().date()
    selected_month = int(request.GET.get('month', today.month))
    selected_year = int(request.GET.get('year', today.year))
    selected_period_label = f"{calendar.month_name[selected_month]} {selected_year}"

    total_employees = Employee.objects.filter(is_active=True).count()
    total_inactive = Employee.objects.filter(is_active=False).count()

    role_breakdown = list(
        Employee.objects.filter(is_active=True)
        .values('role')
        .annotate(count=Count('id'))
        .order_by('role')
    )
    role_labels = [dict(Employee.ROLE_CHOICES).get(r['role'], r['role']) for r in role_breakdown]
    role_counts = [r['count'] for r in role_breakdown]

    this_month_enrollments = StudentEnrollment.objects.filter(
        confirmed_on__year=selected_year, confirmed_on__month=selected_month
    ).count()
    this_month_incentives = StudentEnrollment.objects.filter(
        confirmed_on__year=selected_year, confirmed_on__month=selected_month
    ).aggregate(total=Sum('incentive_amount'))['total'] or 0

    incentive_months = []
    incentive_totals = []
    for i in range(5, -1, -1):
        month = selected_month - i
        year = selected_year
        while month <= 0:
            month += 12
            year -= 1
        total = StudentEnrollment.objects.filter(
            confirmed_on__year=year, confirmed_on__month=month
        ).aggregate(total=Sum('incentive_amount'))['total'] or 0
        incentive_months.append(f"{calendar.month_abbr[month]} {year}")
        incentive_totals.append(float(total))

    top_counselors = list(
        StudentEnrollment.objects.filter(confirmed_on__year=selected_year)
        .values('counselor__name')
        .annotate(total=Sum('incentive_amount'), enrollments=Count('id'))
        .order_by('-total')[:5]
    )
    counselor_labels = [c['counselor__name'] for c in top_counselors]
    counselor_totals = [float(c['total']) for c in top_counselors]

    leaves_this_month = Leave.objects.filter(date__year=selected_year, date__month=selected_month).count()
    deducted_leaves_this_month = Leave.objects.filter(
        date__year=selected_year, date__month=selected_month, is_deducted=True
    ).count()

    this_month_payroll_total = Payroll.objects.filter(
        month=selected_month, year=selected_year
    ).aggregate(total=Sum('net_pay'))['total'] or 0

    active_employees = Employee.objects.filter(is_active=True).order_by('name')
    attendance_labels = []
    attendance_present = []
    attendance_leave = []
    attendance_absent = []
    for emp in active_employees:
        month_records = DailyAttendance.objects.filter(
            employee=emp, date__year=selected_year, date__month=selected_month
        )
        attendance_labels.append(emp.name)
        attendance_present.append(month_records.filter(status='present').count())
        attendance_leave.append(month_records.filter(status='leave').count())
        attendance_absent.append(month_records.filter(status='absent').count())

    attendance_trend_months = []
    attendance_trend_present = []
    attendance_trend_leave = []
    attendance_trend_absent = []
    for i in range(5, -1, -1):
        month = selected_month - i
        year = selected_year
        while month <= 0:
            month += 12
            year -= 1
        month_qs = DailyAttendance.objects.filter(date__year=year, date__month=month)
        attendance_trend_months.append(f"{calendar.month_abbr[month]} {year}")
        attendance_trend_present.append(month_qs.filter(status='present').count())
        attendance_trend_leave.append(month_qs.filter(status='leave').count())
        attendance_trend_absent.append(month_qs.filter(status='absent').count())

    counselor_of_month = None
    counselor_of_month_count = 0
    top_by_count = (
        StudentEnrollment.objects.filter(
            confirmed_on__year=selected_year, confirmed_on__month=selected_month
        )
        .values('counselor')
        .annotate(count=Count('id'))
        .order_by('-count')
        .first()
    )
    if top_by_count and top_by_count['count'] > 0:
        counselor_of_month = Employee.objects.filter(pk=top_by_count['counselor']).first()
        counselor_of_month_count = top_by_count['count']

    month_options = []
    for i in range(12):
        month = today.month - i
        year = today.year
        while month <= 0:
            month += 12
            year -= 1
        month_options.append({'month': month, 'year': year, 'label': f"{calendar.month_name[month]} {year}"})

    context = {
        'total_employees': total_employees,
        'total_inactive': total_inactive,
        'role_labels_json': json.dumps(role_labels, cls=DjangoJSONEncoder),
        'role_counts_json': json.dumps(role_counts, cls=DjangoJSONEncoder),
        'this_month_enrollments': this_month_enrollments,
        'this_month_incentives': this_month_incentives,
        'incentive_months_json': json.dumps(incentive_months, cls=DjangoJSONEncoder),
        'incentive_totals_json': json.dumps(incentive_totals, cls=DjangoJSONEncoder),
        'counselor_labels_json': json.dumps(counselor_labels, cls=DjangoJSONEncoder),
        'counselor_totals_json': json.dumps(counselor_totals, cls=DjangoJSONEncoder),
        'leaves_this_month': leaves_this_month,
        'deducted_leaves_this_month': deducted_leaves_this_month,
        'this_month_payroll_total': this_month_payroll_total,
        'attendance_labels_json': json.dumps(attendance_labels, cls=DjangoJSONEncoder),
        'attendance_present_json': json.dumps(attendance_present, cls=DjangoJSONEncoder),
        'attendance_leave_json': json.dumps(attendance_leave, cls=DjangoJSONEncoder),
        'attendance_absent_json': json.dumps(attendance_absent, cls=DjangoJSONEncoder),
        'attendance_trend_months_json': json.dumps(attendance_trend_months, cls=DjangoJSONEncoder),
        'attendance_trend_present_json': json.dumps(attendance_trend_present, cls=DjangoJSONEncoder),
        'attendance_trend_leave_json': json.dumps(attendance_trend_leave, cls=DjangoJSONEncoder),
        'attendance_trend_absent_json': json.dumps(attendance_trend_absent, cls=DjangoJSONEncoder),
        'selected_month': selected_month,
        'selected_year': selected_year,
        'selected_period_label': selected_period_label,
        'month_options': month_options,
        'has_role_data': any(role_counts),
        'has_incentive_trend_data': any(incentive_totals),
        'has_counselor_data': any(counselor_totals),
        'has_attendance_data': any(attendance_present) or any(attendance_leave) or any(attendance_absent),
        'has_attendance_trend_data': any(attendance_trend_present) or any(attendance_trend_leave) or any(attendance_trend_absent),
        'counselor_of_month': counselor_of_month,
        'counselor_of_month_count': counselor_of_month_count,
    }
    return render(request, 'dashboard/home.html', context)


@login_required
def counselor_of_month_certificate(request, employee_id, year, month):
    from django.http import HttpResponse
    from reportlab.lib.pagesizes import landscape, A4
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor
    from reportlab.pdfgen import canvas as pdf_canvas

    employee = get_object_or_404(Employee, pk=employee_id)

    period_label = f"{calendar.month_name[month]} {year}"
    enrollment_count = StudentEnrollment.objects.filter(
        counselor=employee, confirmed_on__year=year, confirmed_on__month=month
    ).count()

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Certificate_{employee.employee_id}_{month}_{year}.pdf"'

    PRIMARY = HexColor('#063fb0')
    SECONDARY = HexColor('#dbe803')
    DARK = HexColor('#0a1e4d')

    c = pdf_canvas.Canvas(response, pagesize=landscape(A4))
    width, height = landscape(A4)

    c.setFillColor(DARK)
    c.rect(0, 0, width, height, fill=1, stroke=0)
    c.setFillColor(HexColor('#ffffff'))
    margin = 12 * mm
    c.rect(margin, margin, width - 2 * margin, height - 2 * margin, fill=1, stroke=0)
    c.setStrokeColor(SECONDARY)
    c.setLineWidth(3)
    c.rect(margin + 4 * mm, margin + 4 * mm, width - 2 * margin - 8 * mm, height - 2 * margin - 8 * mm, fill=0, stroke=1)

    c.setFillColor(PRIMARY)
    c.setFont("Helvetica-Bold", 26)
    c.drawCentredString(width / 2, height - 45 * mm, "ALHAM OVERSEAS CONSULTANTS")

    c.setFillColor(DARK)
    c.setFont("Helvetica-Bold", 34)
    c.drawCentredString(width / 2, height - 70 * mm, "CERTIFICATE OF RECOGNITION")

    c.setFont("Helvetica", 14)
    c.setFillColor(HexColor('#4b5563'))
    c.drawCentredString(width / 2, height - 85 * mm, "This certificate is proudly presented to")

    c.setFillColor(PRIMARY)
    c.setFont("Helvetica-Bold", 30)
    c.drawCentredString(width / 2, height - 100 * mm, employee.name)

    c.setFont("Helvetica", 13)
    c.setFillColor(HexColor('#374151'))
    c.drawCentredString(
        width / 2, height - 112 * mm,
        f"for being Counselor of the Month — {period_label}"
    )
    c.drawCentredString(
        width / 2, height - 120 * mm,
        f"with {enrollment_count} student enrollment{'s' if enrollment_count != 1 else ''} confirmed this month"
    )

    c.setFont("Helvetica-Oblique", 11)
    c.setFillColor(HexColor('#6b7280'))
    c.drawCentredString(width / 2, margin + 20 * mm, "ALHAM HRM — Recognizing outstanding performance")

    c.setStrokeColor(SECONDARY)
    c.setLineWidth(1)
    c.line(width / 2 - 40 * mm, margin + 30 * mm, width / 2 + 40 * mm, margin + 30 * mm)

    c.showPage()
    c.save()
    return response