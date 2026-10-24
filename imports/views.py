import os
import re
import uuid
from django.conf import settings
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.shortcuts import get_object_or_404, render, redirect
from django.core.exceptions import ValidationError
from django.db import transaction
from django.views.decorators.http import require_POST

from core.middleware import is_admin_user
from .forms import ExcelUploadForm
from .utils import parse_enrollment_workbook, parse_attendance_workbook
from employees.models import Employee
from payroll.models import IncentiveRule, StudentEnrollment
from attendance.models import DailyAttendance, Leave

TEMP_DIR = os.path.join(settings.MEDIA_ROOT, 'import_temp')
admin_required = user_passes_test(is_admin_user, login_url='login')


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
@admin_required
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
@admin_required
@require_POST
def enrollment_import_confirm(request):
    token = request.POST.get('token')
    if not token or re.fullmatch(r'[0-9a-f]{32}', token) is None:
        messages.error(request, 'Upload session expired, please upload the file again.')
        return redirect('enrollment_import')
    path = _temp_path(token)
    if not os.path.exists(path):
        messages.error(request, 'Upload session expired, please upload the file again.')
        return redirect('enrollment_import')

    with open(path, 'rb') as f:
        sheets = parse_enrollment_workbook(f)

    created_count = 0
    skipped_count = 0
    duplicate_count = 0
    unassigned_count = 0
    countries_missing_rule = set()

    with transaction.atomic():  # all or nothing, so a failure halfway can't leave half a file imported
        for sheet_index, sheet in enumerate(sheets):
            counselor = Employee.objects.filter(pk=request.POST.get(f'counselor_{sheet_index}') or None).first()
            if counselor is None:
                unassigned_count += len(sheet['rows'])
                continue

            for row in sheet['rows']:
                if row['problem']:
                    skipped_count += 1
                    continue
                # The same student, country and date for the same counselor is the same enrollment:
                # re-uploading a file must not double anyone's incentive.
                if StudentEnrollment.objects.filter(
                        counselor=counselor, student_name__iexact=row['student_name'],
                        destination_country__iexact=row['country'], confirmed_on=row['confirmed_on']).exists():
                    duplicate_count += 1
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
    if duplicate_count:
        msg += f" {duplicate_count} were already imported before and were left as they are."
    if skipped_count:
        msg += f" Skipped {skipped_count} row(s) with a missing country, an unreadable date or a future date (marked red in the preview)."
    if unassigned_count:
        msg += f" {unassigned_count} row(s) on sheets with no counselor chosen were not imported."
    messages.success(request, msg)
    if countries_missing_rule:
        messages.warning(request, f"No incentive rule set for: {', '.join(sorted(countries_missing_rule))}. Those enrollments were imported with PKR 0 incentive, add a rule and regenerate payroll once set.")

    return redirect('enrollment_list')


@login_required
@admin_required
def attendance_import(request):
    if request.method == 'POST' and 'file' in request.FILES:
        form = ExcelUploadForm(request.POST, request.FILES)
        if form.is_valid():
            result = parse_attendance_workbook(form.cleaned_data['file'])
            if result.get('error'):
                messages.error(request, result['error'])
                return render(request, 'imports/attendance_upload.html', {'form': form})

            counts = {'present': 0, 'leave': 0, 'holiday': 0, 'absent': 0, 'needs_review': 0}
            skipped_unmatched = 0
            already_recorded = 0

            with transaction.atomic():
                for entry in result['entries']:
                    employee = entry['employee']
                    if employee is None:
                        skipped_unmatched += 1
                        continue

                    # Lateness is worked out from the check-in time when the record is saved.
                    obj, created = DailyAttendance.objects.get_or_create(
                        employee=employee, date=entry['date'],
                        defaults={
                            'check_in_time': entry['check_in_time'],
                            'status': entry['status'],
                            'note': entry['note'],
                            'imported': True,
                        }
                    )
                    if not created:
                        already_recorded += 1
                        continue
                    counts[entry['status']] += 1
                    if entry['status'] == 'leave':
                        Leave.objects.get_or_create(
                            employee=employee, date=entry['date'],
                            defaults={'leave_type': 'casual', 'reason': 'Imported from attendance sheet'}
                        )

            msg = (f"Imported attendance for {result['month']}/{result['year']}: "
                   f"{counts['present']} present, {counts['leave']} leave, {counts['absent']} absent, "
                   f"{counts['holiday']} holiday, {counts['needs_review']} flagged for review.")
            if already_recorded:
                msg += (f" {already_recorded} day(s) were already recorded (by check-in or an earlier import) "
                        "and were left unchanged.")
            if result['skipped_future']:
                msg += f" {result['skipped_future']} future day(s) were ignored."
            messages.success(request, msg)
            if result['unmatched_names']:
                messages.warning(request, f"Columns not matched to any employee: {', '.join(result['unmatched_names'])}. Add these employees first, then re-import.")
            if skipped_unmatched:
                messages.warning(request, f"{skipped_unmatched} cell(s) skipped because the employee column couldn't be matched.")

            return redirect('attendance_review')
    else:
        form = ExcelUploadForm()
    return render(request, 'imports/attendance_upload.html', {'form': form})


@login_required
@admin_required
def attendance_review(request):
    records = DailyAttendance.objects.filter(status='needs_review').select_related('employee')
    return render(request, 'imports/attendance_review.html', {'records': records})


@login_required
@admin_required
@require_POST
def attendance_resolve(request, pk):
    record = get_object_or_404(DailyAttendance, pk=pk)
    if request.method == 'POST':
        new_status = request.POST.get('status')
        if new_status not in ('present', 'leave', 'absent', 'holiday'):
            messages.error(request, 'Choose Present, Leave, Absent or Holiday.')
            return redirect('attendance_review')
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
        elif new_status == 'holiday':
            record.status = 'holiday'
        record.save()
        messages.success(request, 'Attendance record resolved.')
    return redirect('attendance_review')