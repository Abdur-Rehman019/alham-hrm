# ALHAM HRM

## What's included
- core: login/logout, base template, professional sidebar layout
- employees: employee records with auto-generated ID (ALHAM-EMP-0001...), full validation, detail page
- attendance: leave logging with the 2-free-leaves-per-month rule and automatic deduction flagging
- payroll: incentive rules (per destination country), student enrollments, automatic payroll/payslip generation
- dashboard: home page with live charts (staff by role, incentive trends, top counselors, attendance snapshot)

## Merging into your existing project (recommended, keeps your data)

Your existing `employees` table schema already matches this build exactly, so you do NOT need to lose your current data.

1. Copy these new folders into your project root: `attendance/`, `payroll/`, `dashboard/`
2. Replace your existing `employees/` folder's `models.py`, `forms.py`, `views.py`, `urls.py`, `admin.py` with the versions here
3. Replace your `core/` folder's `urls.py` and `views.py` with the versions here
4. Replace your `templates/` folder entirely with the one here (it now includes employees, attendance, payroll, dashboard templates plus an upgraded base.html and login.html)
5. Replace `alham_hrm/settings.py` and `alham_hrm/urls.py` with the versions here
6. In your terminal, with your venv active, run:
   ```
   python manage.py makemigrations attendance payroll
   python manage.py migrate
   python manage.py runserver
   ```

Your existing employees, and your existing superuser login, stay exactly as they are. Only new tables (attendance, payroll, incentive rules, enrollments) get added.

## Starting fresh instead

If you'd rather just replace everything:
1. Extract this whole folder
2. Create a fresh venv, `pip install -r requirements.txt`
3. `python manage.py migrate`
4. `python manage.py createsuperuser`
5. `python manage.py runserver`

## First things to do after setup
1. Log in and go to Payroll > Incentive Rules, add a rule for Turkiye (10,000 PKR) and any other destinations you pay incentives for
2. Add your real employees under Employees
3. Log any leave under Attendance
4. Record confirmed enrollments under Enrollments, the incentive amount is assigned automatically from your rules
5. Generate payroll for an employee under Payroll, base salary minus leave deduction plus incentives, calculated automatically
