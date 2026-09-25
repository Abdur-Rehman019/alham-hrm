import datetime
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.utils import timezone

phone_validator = RegexValidator(
    regex=r'^\+?[0-9]{10,15}$',
    message="Enter a valid phone number (10 to 15 digits, optional + prefix)."
)

cnic_validator = RegexValidator(
    regex=r'^\d{5}-\d{7}-\d{1}$',
    message="Enter CNIC in the format 12345-1234567-1."
)


class Employee(models.Model):
    ROLE_CHOICES = [
        ('counselor', 'Counselor'),
        ('processing_officer', 'Processing Officer'),
        ('admin_staff', 'Admin Staff'),
        ('other', 'Other'),
    ]

    employee_id = models.CharField(max_length=20, unique=True, editable=False, blank=True)
    name = models.CharField(max_length=100)
    cnic = models.CharField(max_length=15, blank=True, null=True, unique=True, validators=[cnic_validator])
    date_of_birth = models.DateField(blank=True, null=True)
    role = models.CharField(max_length=30, choices=ROLE_CHOICES)
    monthly_salary = models.DecimalField(max_digits=10, decimal_places=2)
    phone = models.CharField(max_length=20, blank=True, validators=[phone_validator])
    email = models.EmailField(blank=True, unique=True, null=True)
    address = models.CharField(max_length=255, blank=True)
    joined_on = models.DateField()
    leaving_date = models.DateField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    photo = models.ImageField(upload_to='employee_photos/', blank=True, null=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='employee_profile'
    )

    def clean(self):
        super().clean()
        errors = {}
        today = timezone.now().date()

        if not self.name or not self.name.strip():
            errors['name'] = 'Name cannot be empty.'
        elif any(char.isdigit() for char in self.name):
            errors['name'] = 'Name cannot contain numbers.'

        if self.monthly_salary is not None and self.monthly_salary <= 0:
            errors['monthly_salary'] = 'Salary must be greater than zero.'

        if self.joined_on:
            if self.joined_on > today:
                errors['joined_on'] = 'Joining date cannot be in the future.'
            elif self.joined_on < datetime.date(2015, 1, 1):
                errors['joined_on'] = 'Joining date looks too far in the past, please check.'

        if self.date_of_birth:
            if self.date_of_birth > today:
                errors['date_of_birth'] = 'Date of birth cannot be in the future.'
            else:
                age = today.year - self.date_of_birth.year - (
                    (today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day)
                )
                if age < 18:
                    errors['date_of_birth'] = 'Employee must be at least 18 years old.'

        if self.leaving_date:
            if self.leaving_date > today:
                errors['leaving_date'] = 'Leaving date cannot be in the future.'
            if self.joined_on and self.leaving_date < self.joined_on:
                errors['leaving_date'] = 'Leaving date cannot be before the joining date.'

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()

        if self.leaving_date and self.leaving_date <= timezone.now().date():
            self.is_active = False

        if not self.employee_id:
            with transaction.atomic():
                super().save(*args, **kwargs)
                self.employee_id = f"ALHAM-EMP-{self.id:04d}"
                kwargs['force_insert'] = False
                super().save(update_fields=['employee_id'])
        else:
            super().save(*args, **kwargs)

    def current_month_leaves(self):
        today = timezone.now().date()
        return self.leaves.filter(
            date__year=today.year, 
            date__month=today.month
        ).count()

    def total_incentives(self):
        return self.enrollments.aggregate(
            total=models.Sum('incentive_amount')
        )['total'] or 0

    def __str__(self):
        return f"{self.employee_id} - {self.name}"

    class Meta:
        ordering = ['name']