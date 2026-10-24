import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import AuditLog
from employees.models import Employee
from payroll.models import IncentiveRule
from payroll.views import _calculate_and_save_payroll

PW = 'Str0ng!Pass#2026'


class AuditLogTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('boss', 'boss@alham.pk', PW)
        self.client.force_login(self.admin)
        self.employee = Employee.objects.create(name='Ana Khan', role='counselor', monthly_salary=30000,
                                                joined_on=datetime.date(2024, 1, 1), email='ana@alham.pk')
        AuditLog.objects.all().delete()

    def _edit(self, **changes):
        data = {'name': self.employee.name, 'role': self.employee.role, 'monthly_salary': self.employee.monthly_salary,
                'email': self.employee.email, 'joined_on': '2024-01-01', 'is_active': 'on', 'cnic': '', 'phone': '',
                'address': '', 'date_of_birth': '', 'leaving_date': ''}
        data.update(changes)
        return self.client.post(f'/employees/{self.employee.pk}/edit/', data, REMOTE_ADDR='203.0.113.9')

    def test_salary_change_records_who_old_new_and_ip(self):
        self._edit(monthly_salary='45000')
        entry = AuditLog.objects.get(action='update', category='employee')
        self.assertEqual(entry.actor, self.admin)
        self.assertEqual(entry.actor_name, 'boss')
        self.assertEqual(entry.ip_address, '203.0.113.9')
        self.assertEqual(entry.changes, {'monthly_salary': ['30000', '45000']})
        self.assertIn('Ana Khan', entry.object_repr)

    def test_saving_without_changes_records_nothing(self):
        self._edit()
        self.assertFalse(AuditLog.objects.exists())

    def test_payroll_generation_and_approval_are_recorded(self):
        today = timezone.localdate()
        payroll, _ = _calculate_and_save_payroll(self.employee, today.year, today.month)
        self.assertTrue(AuditLog.objects.filter(category='payroll', action='create').exists())
        self.client.post(f'/payroll/payslip/{payroll.pk}/approve/')
        self.assertTrue(AuditLog.objects.filter(category='payroll', action='approve', actor=self.admin).exists())
        self.assertTrue(AuditLog.objects.filter(category='payroll', action='payslip').exists())

    def test_incentive_rule_create_and_delete(self):
        rule = IncentiveRule.objects.create(destination_country='Turkey', amount=Decimal('5000'))
        rule.delete()
        self.assertEqual(list(AuditLog.objects.filter(category='incentive').values_list('action', flat=True)),
                         ['delete', 'create'])

    def test_login_password_change_hides_the_value(self):
        user = User.objects.create_user('ana', password=PW)
        AuditLog.objects.all().delete()
        user.set_password('An0ther!Pass#2026')
        user.save()
        entry = AuditLog.objects.get(category='account')
        self.assertEqual(entry.changes, {'password': ['(hidden)', '(changed)']})

    def test_sign_in_alone_is_not_logged_as_a_change(self):
        user = User.objects.create_user('ana', password=PW)
        AuditLog.objects.all().delete()
        user.last_login = timezone.now()
        user.save(update_fields=['last_login'])
        self.assertFalse(AuditLog.objects.exists())

    def test_page_is_admin_only_and_read_only_in_django_admin(self):
        self._edit(monthly_salary='45000')
        page = self.client.get('/accounts/audit-log/?category=employee')
        self.assertContains(page, '45000')
        entry = AuditLog.objects.first()
        self.assertEqual(self.client.get(f'/admin/core/auditlog/{entry.pk}/delete/').status_code, 403)

        user = User.objects.create_user('ana', password=PW)
        Employee.objects.filter(pk=self.employee.pk).update(user=user)
        self.client.force_login(user)
        self.assertRedirects(self.client.get('/accounts/audit-log/'), '/attendance/portal/', fetch_redirect_response=False)
