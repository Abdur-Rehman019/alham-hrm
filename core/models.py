from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """
    Who changed what, and when: employees, salaries, payroll, incentives and login accounts.
    Written automatically (see core/audit.py); never edited or deleted through the app.
    """
    CATEGORY_CHOICES = [
        ('employee', 'Employee'),
        ('payroll', 'Payroll'),
        ('incentive', 'Incentives'),
        ('account', 'Login account'),
    ]
    ACTION_CHOICES = [
        ('create', 'Created'),
        ('update', 'Changed'),
        ('delete', 'Deleted'),
        ('approve', 'Approved'),
        ('payslip', 'Payslip email'),
        ('security', 'Security'),
    ]

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                              related_name='+')
    actor_name = models.CharField(max_length=150, help_text='Kept even if the account is deleted later.')
    ip_address = models.CharField(max_length=45, blank=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, db_index=True)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    object_type = models.CharField(max_length=50)
    object_id = models.CharField(max_length=50, blank=True)
    object_repr = models.CharField(max_length=200)
    changes = models.JSONField(default=dict, blank=True, help_text='{field: [old, new]}')
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['object_type', 'object_id'])]

    def __str__(self):
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor_name} {self.get_action_display()} {self.object_repr}"
