import os
import uuid
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect
from django.core.exceptions import ValidationError
from .forms import ExcelUploadForm
from .utils import parse_enrollment_workbook, parse_attendance_workbook
from employees.models import Employee
from payroll.models import IncentiveRule, StudentEnrollment
from attendance.models import DailyAttendance, Leave

TEMP_DIR = os.path.join(settings.MEDIA_ROOT, 'import_temp')


def _save_temp(uploaded_file):
    os.makedirs(TEMP_DIR, exist_ok=True)
    token = uuid.uuid4().hex
    path = os.path.join(TEMP_DIR, f"{token}.xlsx")
    with open(path, 'wb') as f:
        for chunk in uploaded_file.chunks():
            f.write(chunk)
    return token


def _temp_path(token):
    return os.path.join(TEMP_DIR, f"{token}.xlsx")


@login_required
def enrollment_import(request):
    if request.method == 'POST' and 'file' in request.FILES:
        form = ExcelUploadForm(request.POST, request.FILES)
        if form.is_valid():
            token = _save_temp(form.cleaned_data['file'])
            with open(_temp_path(token), 'rb') as f:
                sheets = parse_enrollment_workbook(f)
            active_employees = Employee.objects.filter(is_active=True)
            return render(request, 'imports/enrollment_preview.html', {
                'sheets': sheets, 'token': token, 'employees': active_employees,
            })
    else:
        form = ExcelUploadForm()
    return render(request, 'imports/enrollment_upload.html', {'form': form})


@login_required
def enrollment_import_confirm(request):
    if request.method != 'POST':
        return redirect('enrollment_import')

    token = request.POST.get('token')
    path = _temp_path(token)
    if not os.path.exists(path):
        messages.error(request, 'Upload session expired, please upload the file again.')
        return redirect('enrollment_import')

    with open(path, 'rb') as f:
        sheets = parse_enrollment_workbook(f)

    created_count = 0
    skipped_count = 0
    countries_missing_rule = set()

    for sheet_index, sheet in enumerate(sheets):
        counselor_id = request.POST.get(f'counselor_{sheet_index}')
        if not counselor_id:
            skipped_count += len(sheet['rows'])
            continue
        try:
            counselor = Employee.objects.get(pk=counselor_id)
        except Employee.DoesNotExist:
            skipped_count += len(sheet['rows'])
            continue

        for row in sheet['rows']:
            if row['date_error'] or not row['country']:
                skipped_count += 1
                continue
            if not IncentiveRule.objects.filter(destination_country__iexact=row['country']).exists():
                countries_missing_rule.add(row['country'])

            enrollment = StudentEnrollment(
                student_name=row['student_name'],
                destination_country=row['country'],
                counselor=counselor,
                confirmed_on=row['confirmed_on'],
            )
            try:
                enrollment.full_clean()
                enrollment.save()
                created_count += 1
            except ValidationError:
                skipped_count += 1

    os.remove(path)

    msg = f"Imported {created_count} enrollment(s)."
    if skipped_count:
        msg += f" Skipped {skipped_count} row(s) (missing counselor assignment, bad date, or duplicate)."
    messages.success(request, msg)
    if countries_missing_rule:
        messages.warning(request, f"No incentive rule set for: {', '.join(sorted(countries_missing_rule))}. Those enrollments were imported with PKR 0 incentive, add a rule and regenerate payroll once set.")

    return redirect('enrollment_list')


@login_required
def attendance_import(request):
    if request.method == 'POST' and 'file' in request.FILES:
        form = ExcelUploadForm(request.POST, request.FILES)
        if form.is_valid():
            result = parse_attendance_workbook(form.cleaned_data['file'])
            if result.get('error'):
                messages.error(request, result['error'])
                return render(request, 'imports/attendance_upload.html', {'form': form})

            created_present = 0
            created_leave = 0
            created_holiday = 0
            needs_review = 0
            skipped_unmatched = 0

            for entry in result['entries']:
                employee = entry['employee']
                if employee is None:
                    skipped_unmatched += 1
                    continue

                obj, created = DailyAttendance.objects.get_or_create(
                    employee=employee, date=entry['date'],
                    defaults={
                        'check_in_time': entry['check_in_time'],
                        'status': entry['status'],
                        'is_late': entry['is_late'],
                        'note': entry['note'],
                        'imported': True,
                    }
                )
                if not created:
                    continue

                if entry['status'] == 'present':
                    created_present += 1
                elif entry['status'] == 'holiday':
                    created_holiday += 1
                elif entry['status'] == 'needs_review':
                    needs_review += 1
                elif entry['status'] == 'leave':
                    created_leave += 1
                    Leave.objects.get_or_create(
                        employee=employee, date=entry['date'],
                        defaults={'leave_type': 'casual', 'reason': 'Imported from attendance sheet'}
                    )

            messages.success(
                request,
                f"Imported attendance for {result['month']}/{result['year']}: "
                f"{created_present} present, {created_leave} leave, {created_holiday} holiday, "
                f"{needs_review} flagged for review."
            )
            if result['unmatched_names']:
                messages.warning(request, f"Columns not matched to any employee: {', '.join(result['unmatched_names'])}. Add these employees first, then re-import.")
            if skipped_unmatched:
                messages.warning(request, f"{skipped_unmatched} cell(s) skipped because the employee column couldn't be matched.")

            return redirect('attendance_review')
    else:
        form = ExcelUploadForm()
    return render(request, 'imports/attendance_upload.html', {'form': form})


@login_required
def attendance_review(request):
    records = DailyAttendance.objects.filter(status='needs_review').select_related('employee')
    return render(request, 'imports/attendance_review.html', {'records': records})


@login_required
def attendance_resolve(request, pk):
    record = DailyAttendance.objects.get(pk=pk)
    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status == 'leave':
            record.status = 'leave'
            Leave.objects.get_or_create(
                employee=record.employee, date=record.date,
                defaults={'leave_type': 'casual', 'reason': 'Resolved from attendance import review'}
            )
        elif new_status == 'present':
            record.status = 'present'
        elif new_status == 'absent':
            record.status = 'absent'
        record.save()
        messages.success(request, 'Attendance record resolved.')
    return redirect('attendance_review')