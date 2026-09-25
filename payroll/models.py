from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from employees.models import Employee


class IncentiveRule(models.Model):
    destination_country = models.CharField(max_length=50, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    def clean(self):
        errors = {}
        if self.amount is not None and self.amount <= 0:
            errors['amount'] = 'Incentive amount must be greater than zero.'
        if self.destination_country:
            existing = IncentiveRule.objects.filter(
                destination_country__iexact=self.destination_country.strip()
            ).exclude(pk=self.pk)
            if existing.exists():
                errors['destination_country'] = f'A rule for "{existing.first().destination_country}" already exists. Edit that rule instead of adding a new one.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.destination_country:
            self.destination_country = self.destination_country.strip().title()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.destination_country} - PKR {self.amount}"

class StudentEnrollment(models.Model):
    student_name = models.CharField(max_length=100)
    destination_country = models.CharField(max_length=50)
    counselor = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='enrollments')
    confirmed_on = models.DateField()
    incentive_amount = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    incentive_paid = models.BooleanField(default=False)

    class Meta:
        ordering = ['-confirmed_on']

    def clean(self):
        if self.confirmed_on and self.confirmed_on > timezone.now().date():
            raise ValidationError({'confirmed_on': 'Confirmation date cannot be in the future.'})

    def save(self, *args, **kwargs):
        if not self.incentive_amount:
            rule = IncentiveRule.objects.filter(destination_country=self.destination_country).first()
            self.incentive_amount = rule.amount if rule else 0
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student_name} -> {self.destination_country} ({self.counselor.name})"


class Payroll(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='payrolls')
    month = models.PositiveSmallIntegerField()
    year = models.PositiveSmallIntegerField()
    base_salary = models.DecimalField(max_digits=10, decimal_places=2)
    leave_deduction = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    incentive_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    net_pay = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    generated_on = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('employee', 'month', 'year')
        ordering = ['-year', '-month']

    def save(self, *args, **kwargs):
        self.net_pay = self.base_salary - self.leave_deduction + self.incentive_total
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.employee.name} - {self.month}/{self.year}"
