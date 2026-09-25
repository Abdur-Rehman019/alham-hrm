import calendar
import random
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from employees.models import Employee
from attendance.models import Leave, DailyAttendance
from payroll.models import IncentiveRule, StudentEnrollment, Payroll


DEMO_EMPLOYEES = [
    ("Hina Malik", "counselor", 42000),
    ("Usman Tariq", "counselor", 45000),
    ("Sara Yousaf", "counselor", 40000),
    ("Bilal Chaudhry", "processing_officer", 48000),
    ("Fatima Noor", "processing_officer", 46000),
    ("Kamran Sheikh", "admin_staff", 38000),
]

DESTINATIONS = {
    "Turkey": 10000,
    "Sweden": 12000,
    "Denmark": 12000,
    "Cyprus": 8000,
    "New Zealand": 15000,
    "UK": 20000,
}

FIRST_NAMES = ["Ahmed", "Ali", "Zainab", "Hassan", "Ayesha", "Bilal", "Sana", "Omar",
               "Mahnoor", "Hamza", "Iqra", "Danish", "Rabia", "Saad", "Nimra"]
LAST_NAMES = ["Khan", "Malik", "Raza", "Sheikh", "Butt", "Chaudhry", "Iqbal", "Farooq"]


class Command(BaseCommand):
    help = (
        "Populates realistic demo data across the last 6 months: employees, daily "
        "attendance, leaves, student enrollments, incentives and payroll. "
        "Intended for a test/demo database, not for mixing into real production data "
        "you care about, since it adds clearly-named demo employees alongside "
        "whatever is already there."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--months', type=int, default=6,
            help='How many months of history to generate (default 6).'
        )

    def handle(self, *args, **options):
        months_back = options['months']
        random.seed(42)

        employees = self._ensure_employees()
        self._ensure_incentive_rules()

        today = timezone.now().date()
        for i in range(months_back - 1, -1, -1):
            month = today.month - i
            year = today.year
            while month <= 0:
                month += 12
                year -= 1
            self.stdout.write(f"Generating data for {calendar.month_name[month]} {year}...")
            self._generate_month(employees, year, month)

        self.stdout.write(self.style.SUCCESS(
            f"Demo data generated for {len(employees)} employees across {months_back} months."
        ))

    def _ensure_employees(self):
        employees = []
        existing_names = set(Employee.objects.values_list('name', flat=True))
        base_date = date(2023, 6, 1)
        for name, role, salary in DEMO_EMPLOYEES:
            if name in existing_names:
                employees.append(Employee.objects.get(name=name))
                continue
            emp = Employee.objects.create(
                name=name, role=role, monthly_salary=salary,
                joined_on=base_date + timedelta(days=random.randint(0, 300)),
                phone=f"030{random.randint(10000000, 99999999)}",
            )
            employees.append(emp)
        # Include any real active employees already in the system too
        for emp in Employee.objects.filter(is_active=True).exclude(pk__in=[e.pk for e in employees]):
            employees.append(emp)
        return employees

    def _ensure_incentive_rules(self):
        for country, amount in DESTINATIONS.items():
            IncentiveRule.objects.get_or_create(
                destination_country=country, defaults={'amount': amount}
            )

    def _generate_month(self, employees, year, month):
        days_in_month = calendar.monthrange(year, month)[1]
        today = timezone.now().date()

        for emp in employees:
            leave_days_this_month = 0
            for day in range(1, days_in_month + 1):
                the_date = date(year, month, day)
                if the_date > today:
                    continue
                weekday = the_date.weekday()  # 0=Mon ... 6=Sun
                if weekday == 6:  # Sunday holiday
                    DailyAttendance.objects.get_or_create(
                        employee=emp, date=the_date,
                        defaults={'status': 'holiday', 'imported': False}
                    )
                    continue

                roll = random.random()
                if roll < 0.05 and leave_days_this_month < 3:
                    # occasional leave
                    leave_days_this_month += 1
                    Leave.objects.get_or_create(
                        employee=emp, date=the_date,
                        defaults={'leave_type': random.choice(['casual', 'sick']), 'reason': 'Demo data'}
                    )
                    DailyAttendance.objects.get_or_create(
                        employee=emp, date=the_date,
                        defaults={'status': 'leave', 'imported': False}
                    )
                elif roll < 0.07:
                    DailyAttendance.objects.get_or_create(
                        employee=emp, date=the_date,
                        defaults={'status': 'absent', 'imported': False}
                    )
                else:
                    hour = 10 if random.random() < 0.6 else 11
                    minute = random.randint(0, 45)
                    is_late = hour == 11 and minute > 30
                    DailyAttendance.objects.get_or_create(
                        employee=emp, date=the_date,
                        defaults={
                            'status': 'present',
                            'check_in_time': f"{hour:02d}:{minute:02d}:00",
                            'is_late': is_late,
                            'imported': False,
                        }
                    )

            # Enrollments: counselors and processing officers close a handful of students per month
            if emp.role in ('counselor', 'processing_officer'):
                num_enrollments = random.choice([0, 1, 1, 2, 2, 3])
                for _ in range(num_enrollments):
                    student_name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
                    country = random.choice(list(DESTINATIONS.keys()))
                    confirmed_day = random.randint(1, min(days_in_month, today.day if (year, month) == (today.year, today.month) else days_in_month))
                    StudentEnrollment.objects.get_or_create(
                        student_name=student_name, counselor=emp, confirmed_on=date(year, month, confirmed_day),
                        defaults={'destination_country': country}
                    )

            # Payroll for the month
            deducted_leaves = Leave.objects.filter(
                employee=emp, date__year=year, date__month=month, is_deducted=True
            ).count()
            per_day_rate = emp.monthly_salary / days_in_month
            leave_deduction = round(per_day_rate * deducted_leaves, 2)
            incentive_total = sum(
                e.incentive_amount for e in StudentEnrollment.objects.filter(
                    counselor=emp, confirmed_on__year=year, confirmed_on__month=month
                )
            )
            payroll, created = Payroll.objects.get_or_create(
                employee=emp, month=month, year=year,
                defaults={
                    'base_salary': emp.monthly_salary,
                    'leave_deduction': leave_deduction,
                    'incentive_total': incentive_total,
                }
            )
            if not created:
                payroll.base_salary = emp.monthly_salary
                payroll.leave_deduction = leave_deduction
                payroll.incentive_total = incentive_total
                payroll.save()