import calendar

from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as pdf_canvas

from core.middleware import is_admin_user
from employees.models import Employee
from payroll.models import StudentEnrollment


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
    primary = HexColor('#063fb0')
    secondary = HexColor('#dbe803')
    dark = HexColor('#0a1e4d')
    page_size = landscape(A4)
    c = pdf_canvas.Canvas(response, pagesize=page_size)
    width, height = page_size
    c.setFillColor(dark)
    c.rect(0, 0, width, height, fill=1, stroke=0)
    c.setFillColor(HexColor('#ffffff'))
    margin = 12 * mm
    c.rect(margin, margin, width - 2 * margin, height - 2 * margin, fill=1, stroke=0)
    c.setStrokeColor(secondary)
    c.setLineWidth(3)
    c.rect(
        margin + 4 * mm, margin + 4 * mm,
        width - 2 * margin - 8 * mm, height - 2 * margin - 8 * mm,
        fill=0, stroke=1,
    )
    c.setFillColor(primary)
    c.setFont('Helvetica-Bold', 26)
    c.drawCentredString(width / 2, height - 45 * mm, 'ALHAM OVERSEAS CONSULTANTS')
    c.setFillColor(dark)
    c.setFont('Helvetica-Bold', 34)
    c.drawCentredString(width / 2, height - 70 * mm, 'CERTIFICATE OF RECOGNITION')
    c.setFont('Helvetica', 14)
    c.setFillColor(HexColor('#4b5563'))
    c.drawCentredString(width / 2, height - 85 * mm, 'This certificate is proudly presented to')
    c.setFillColor(primary)
    c.setFont('Helvetica-Bold', 30)
    c.drawCentredString(width / 2, height - 100 * mm, employee.name)
    c.setFont('Helvetica', 13)
    c.setFillColor(HexColor('#374151'))
    c.drawCentredString(width / 2, height - 112 * mm, f'for being Counselor of the Month — {period_label}')
    c.drawCentredString(
        width / 2, height - 120 * mm,
        f"with {enrollment_count} student enrollment{'s' if enrollment_count != 1 else ''} confirmed this month",
    )
    c.setFont('Helvetica-Oblique', 11)
    c.setFillColor(HexColor('#6b7280'))
    c.drawCentredString(width / 2, margin + 20 * mm, 'ALHAM HRM — Recognizing outstanding performance')
    c.setStrokeColor(secondary)
    c.setLineWidth(1)
    c.line(width / 2 - 40 * mm, margin + 30 * mm, width / 2 + 40 * mm, margin + 30 * mm)
    c.showPage()
    c.save()
    return response
