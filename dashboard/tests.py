import datetime

from django.contrib.auth.models import User
from django.test import TestCase

from employees.models import Employee
from payroll.models import StudentEnrollment

PW = 'Str0ng!Pass#2026'


class CounselorCertificateTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser('boss', 'boss@alham.pk', PW))
        self.employee = Employee.objects.create(name='Demo - Abdur Rehman', role='counselor', monthly_salary=30000,
                                                joined_on=datetime.date(2024, 1, 1))
        StudentEnrollment.objects.create(student_name='S', destination_country='UK', counselor=self.employee,
                                         confirmed_on=datetime.date(2026, 10, 3))

    def test_pdf_is_generated(self):
        response = self.client.get(f'/certificate/{self.employee.pk}/2026/10/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertIn(b'Counselor of the Month - Abdur Rehman - October 2026', response.content)

    def test_bad_month_and_employee_only(self):
        self.assertEqual(self.client.get(f'/certificate/{self.employee.pk}/2026/13/').status_code, 404)
        user = User.objects.create_user('ana', password=PW)
        Employee.objects.filter(pk=self.employee.pk).update(user=user)
        self.client.force_login(user)
        self.assertEqual(self.client.get(f'/certificate/{self.employee.pk}/2026/10/').status_code, 302)
