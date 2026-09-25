import re
import datetime
import difflib
import openpyxl
from employees.models import Employee


def guess_counselor_name(sheet_name):
    """Strip common prefixes/suffixes from a sheet name to get a likely counselor first name."""
    name = sheet_name
    name = re.sub(r"(?i)^(sir|mam|miss|mr|mrs)\.?\s+", "", name.strip())
    name = re.sub(r"(?i)('?s)?\s+students?$", "", name).strip()
    return name


def match_employee(name_hint, employees_qs):
    """Try to match a name hint against a queryset of employees. Returns (employee_or_none, confidence)."""
    if not name_hint:
        return None, 0
    names = list(employees_qs.values_list('name', flat=True))
    lowered_hint = name_hint.lower()

    for n in names:
        if lowered_hint in n.lower() or n.lower().split()[0] == lowered_hint.lower():
            return employees_qs.get(name=n), 'high'

    close = difflib.get_close_matches(lowered_hint, [n.lower() for n in names], n=1, cutoff=0.6)
    if close:
        for n in names:
            if n.lower() == close[0]:
                return employees_qs.get(name=n), 'fuzzy'
    return None, 0


def parse_date_cell(value):
    """Handle both real datetime cells and 'DD/MM/YYYY' text cells."""
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    if isinstance(value, str):
        value = value.strip()
        for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
            try:
                return datetime.datetime.strptime(value, fmt).date()
            except ValueError:
                continue
    return None


def parse_enrollment_workbook(file_obj):
    """
    Parses a workbook where each sheet is one counselor's students,
    with columns: Name, Enrollment Date, Country.
    Returns a list of sheet result dicts for preview.
    """
    wb = openpyxl.load_workbook(file_obj, data_only=True)
    active_employees = Employee.objects.filter(is_active=True)
    results = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue

        header = [str(c).strip().lower() if c else '' for c in rows[0]]
        try:
            name_idx = next(i for i, h in enumerate(header) if 'name' in h)
            date_idx = next(i for i, h in enumerate(header) if 'date' in h)
            country_idx = next(i for i, h in enumerate(header) if 'country' in h)
        except StopIteration:
            results.append({
                'sheet_name': sheet_name, 'counselor_hint': None, 'matched_employee': None,
                'match_confidence': 0, 'rows': [], 'error': 'Could not find Name/Enrollment Date/Country columns in this sheet.'
            })
            continue

        counselor_hint = guess_counselor_name(sheet_name)
        matched_employee, confidence = match_employee(counselor_hint, active_employees)

        parsed_rows = []
        for row in rows[1:]:
            if not row or not row[name_idx]:
                continue
            student_name = str(row[name_idx]).strip()
            country = str(row[country_idx]).strip() if row[country_idx] else ''
            confirmed_on = parse_date_cell(row[date_idx])
            parsed_rows.append({
                'student_name': student_name,
                'country': country,
                'confirmed_on': confirmed_on,
                'date_error': confirmed_on is None,
            })

        results.append({
            'sheet_name': sheet_name,
            'counselor_hint': counselor_hint,
            'matched_employee': matched_employee,
            'match_confidence': confidence,
            'rows': parsed_rows,
            'error': None,
        })

    return results


def parse_attendance_workbook(file_obj):
    """
    Parses the ALHAM attendance matrix format:
    - A header block containing 'Year' / 'Month:' somewhere near the top
    - A row with employee column numbers, then a row with employee names
    - Data rows: day number, day name, then one cell per employee
    - 'SUNDAY' (or similar) merged rows mean holiday, no per-employee cells
    - Footer rows: Present / Absent / Holiday totals (ignored for import)
    """
    import re as _re
    wb = openpyxl.load_workbook(file_obj, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = list(ws.iter_rows(values_only=True))

    month_num, year_num = None, None
    header_row_idx = None
    for i, row in enumerate(rows[:6]):
        for cell in row:
            if cell and isinstance(cell, str) and 'month' in cell.lower():
                m = _re.search(r'([A-Za-z]+)\s+(\d{4})', cell)
                if m:
                    try:
                        month_num = datetime.datetime.strptime(m.group(1), '%B').month
                    except ValueError:
                        pass
                    year_num = int(m.group(2))
        for cell in row:
            if cell and isinstance(cell, str) and 'date' in cell.lower():
                header_row_idx = i
                break
        if header_row_idx is not None:
            break

    if header_row_idx is None or month_num is None:
        return {'error': 'Could not detect the month/year or header row in this sheet. Please check the file format.'}

    name_row = rows[header_row_idx + 1]
    employee_names = [str(c).strip() for c in name_row if c and str(c).strip()]

    active_employees = Employee.objects.filter(is_active=True)
    employee_map = {}
    for name in employee_names:
        emp, confidence = match_employee(name, active_employees)
        employee_map[name] = emp

    entries = []
    unmatched_names = set()
    for name, emp in employee_map.items():
        if emp is None:
            unmatched_names.add(name)

    data_rows = rows[header_row_idx + 2:]
    for row in data_rows:
        if not row or row[0] is None:
            continue
        day_num = row[0]
        if not isinstance(day_num, (int, float)):
            continue
        day_str = str(row[1]).strip().upper() if len(row) > 1 and row[1] else ''
        try:
            the_date = datetime.date(year_num, month_num, int(day_num))
        except ValueError:
            continue

        if 'SUN' in day_str or all(c is None for c in row[2:2 + len(employee_names)]):
            for name in employee_names:
                entries.append({
                    'employee_name': name, 'employee': employee_map.get(name),
                    'date': the_date, 'status': 'holiday', 'check_in_time': None,
                    'is_late': False, 'note': '', 'raw': None,
                })
            continue

        for col_offset, name in enumerate(employee_names):
            cell_idx = 2 + col_offset
            value = row[cell_idx] if cell_idx < len(row) else None
            entry = {
                'employee_name': name, 'employee': employee_map.get(name),
                'date': the_date, 'raw': value, 'note': '', 'is_late': False,
                'check_in_time': None, 'status': 'present',
            }
            if value is None or (isinstance(value, str) and value.strip() == ''):
                entry['status'] = 'needs_review'
            elif isinstance(value, str) and 'not mention' in value.lower():
                entry['status'] = 'needs_review'
                entry['note'] = 'not mentioned in sheet'
            elif isinstance(value, str) and 'leave' in value.lower():
                entry['status'] = 'leave'
            elif isinstance(value, datetime.time):
                entry['status'] = 'present'
                entry['check_in_time'] = value
            elif isinstance(value, str):
                m = _re.match(r'^\s*(\d{1,2}):(\d{2})', value)
                if m:
                    try:
                        entry['check_in_time'] = datetime.time(int(m.group(1)) % 24, int(m.group(2)))
                        entry['status'] = 'present'
                    except ValueError:
                        entry['status'] = 'needs_review'
                        entry['note'] = value
                    if '(late)' in value.lower() or 'late' in value.lower():
                        entry['is_late'] = True
                        entry['note'] = value
                else:
                    entry['status'] = 'needs_review'
                    entry['note'] = str(value)
            else:
                entry['status'] = 'needs_review'
                entry['note'] = str(value)
            entries.append(entry)

    return {
        'error': None,
        'month': month_num,
        'year': year_num,
        'employee_names': employee_names,
        'unmatched_names': sorted(unmatched_names),
        'entries': entries,
    }