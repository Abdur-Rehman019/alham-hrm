from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from employees.models import Employee

FREE_LEAVES_PER_MONTH = 2


class Leave(models.Model):
    LEAVE_TYPE_CHOICES = [
        ('casual', 'Casual'),
        ('sick', 'Sick'),
        ('other', 'Other'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leaves')
    date = models.DateField()
    leave_type = models.CharField(max_length=20, choices=LEAVE_TYPE_CHOICES, default='casual')
    reason = models.CharField(max_length=255, blank=True)
    is_deducted = models.BooleanField(default=False, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date']
        unique_together = ('employee', 'date')

    def clean(self):
        if self.date and self.date > timezone.now().date():
            raise ValidationError({'date': 'Leave date cannot be in the future.'})

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        if is_new:
            count_this_month = Leave.objects.filter(
                employee=self.employee,
                date__year=self.date.year,
                date__month=self.date.month,
            ).count()
            self.is_deducted = count_this_month >= FREE_LEAVES_PER_MONTH
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.employee.name} - {self.date}"


class DailyAttendance(models.Model):
    STATUS_CHOICES = [
        ('present', 'Present'),
        ('leave', 'Leave'),
        ('absent', 'Absent'),
        ('needs_review', 'Needs Review'),
        ('holiday', 'Holiday'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='daily_attendance')
    date = models.DateField()
    check_in_time = models.TimeField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='present')
    is_late = models.BooleanField(default=False)
    note = models.CharField(max_length=100, blank=True)
    imported = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date']
        unique_together = ('employee', 'date')
        verbose_name_plural = 'Daily attendance'

    def __str__(self):
        return f"{self.employee.name} - {self.date} - {self.status}"