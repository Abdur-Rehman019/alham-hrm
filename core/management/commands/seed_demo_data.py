import calendar
import random
import re
import secrets
from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from attendance.models import Leave, DailyAttendance
from employees.models import Employee
from payroll.calculations import compute_payroll
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
        "Never adds generated records to existing employee profiles."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--months', type=int, default=6,
            help='How many months of history to generate (default 6).'
        )
        parser.add_argument(
            '--create-logins', action='store_true',
            help='Create employee portal logins and print one-time temporary passwords.'
        )
        parser.add_argument(
            '--allow-production', action='store_true',
            help='Explicitly allow seeding PostgreSQL while DEBUG=False. Does not create logins or incentive rules.'
        )

    def handle(self, *args, **options):
        months_back = options['months']
        production_target = not settings.DEBUG and connection.vendor == 'postgresql'
        local_target = settings.DEBUG and connection.vendor == 'sqlite'
        if production_target and not options['allow_production']:
            raise CommandError(
                'Production seeding requires the explicit --allow-production flag.'
            )
        if production_target and options['create_logins']:
            raise CommandError(
                'Demo login creation is disabled for production databases.'
            )
        if not (local_target or (production_target and options['allow_production'])):
            raise CommandError(
                'Demo data can only be generated on local DEBUG SQLite, or on PostgreSQL '
                'with DEBUG=False and the explicit --allow-production flag.'
            )
        if not 1 <= months_back <= 24:
            raise CommandError('--months must be between 1 and 24.')

        random.seed(42)

        with transaction.atomic():
            employees = self._ensure_employees()
            if production_target:
                self.destinations = self._configured_destinations()
            else:
                self._ensure_incentive_rules()
                self.destinations = DESTINATIONS

            if options['create_logins']:
                self._ensure_logins(employees)

            today = timezone.localdate()
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
        base_date = date(2023, 6, 1)
        for name, role, salary in DEMO_EMPLOYEES:
            email_slug = re.sub(r'[^a-z0-9]+', '.', name.lower()).strip('.')
            employee, _ = Employee.objects.get_or_create(
                email=f"demo.{email_slug}@example.invalid",
                defaults={
                    'name': f"Demo - {name}",
                    'role': role,
                    'monthly_salary': salary,
                    'joined_on': base_date + timedelta(days=random.randint(0, 300)),
                    'phone': f"030{random.randint(10000000, 99999999)}",
                },
            )
            employees.append(employee)
        return employees

    def _ensure_logins(self, employees):
        user_model = get_user_model()
        for employee in employees:
            if employee.user_id:
                self.stdout.write(f"{employee.name}: already linked to {employee.user.get_username()}")
                continue

            username_base = f"demo_{re.sub(r'[^a-z0-9]+', '_', employee.name.lower()).strip('_')}"
            username = username_base
            suffix = 2
            while user_model.objects.filter(username=username).exists():
                username = f"{username_base}_{suffix}"
                suffix += 1

            temporary_password = secrets.token_urlsafe(14)
            user = user_model.objects.create_user(
                username=username,
                email=employee.email,
                password=temporary_password,
            )
            employee.user = user
            employee.must_change_password = True
            employee.save(update_fields=['user', 'must_change_password'])
            self.stdout.write(
                self.style.WARNING(
                    f"{employee.name} login: {username} / {temporary_password} "
                    "(temporary; change it at first sign-in)"
                )
            )

    def _ensure_incentive_rules(self):
        for country, amount in DESTINATIONS.items():
            if not IncentiveRule.objects.filter(destination_country__iexact=country).exists():
                IncentiveRule.objects.create(destination_country=country, amount=amount)

    def _configured_destinations(self):
        configured = {
            rule.destination_country.lower(): rule.destination_country
            for rule in IncentiveRule.objects.all()
        }
        return {
            country: amount
            for country, amount in DESTINATIONS.items()
            if country.lower() in configured
        }

    def _generate_month(self, employees, year, month):
        days_in_month = calendar.monthrange(year, month)[1]
        today = timezone.localdate()

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
                    country = random.choice(list(self.destinations.keys()) or list(DESTINATIONS.keys()))
                    confirmed_day = random.randint(1, min(days_in_month, today.day if (year, month) == (today.year, today.month) else days_in_month))
                    StudentEnrollment.objects.get_or_create(
                        student_name=student_name, counselor=emp, confirmed_on=date(year, month, confirmed_day),
                        defaults={'destination_country': country}
                    )

            calculation = compute_payroll(emp, year, month)
            payroll, created = Payroll.objects.get_or_create(
                employee=emp, month=month, year=year,
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
                if amounts_changed:
                    payroll.base_salary = calculation.base_salary
                    payroll.leave_deduction = calculation.leave_deduction
                    payroll.incentive_total = calculation.incentive_total
                    payroll.is_approved = False
                    payroll.approved_at = None
                    payroll.approved_by = None
                    payroll.save()