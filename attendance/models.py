from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from employees.models import Employee

FREE_LEAVES_PER_MONTH = 2


def is_late_check_in(check_in_time):
    """
    Late means after office start plus the grace period: 10:00 + 15 minutes, so 10:15 is still
    on time and 10:16 is late. Seconds are ignored.
    """
    import datetime
    from django.conf import settings
    if not check_in_time:
        return False
    if isinstance(check_in_time, str):
        check_in_time = datetime.time.fromisoformat(check_in_time)
    start = datetime.datetime.combine(datetime.date.today(), settings.OFFICE_START)
    cutoff = (start + datetime.timedelta(minutes=settings.LATE_GRACE_MINUTES)).time()
    return check_in_time.replace(second=0, microsecond=0, tzinfo=None) > cutoff


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
        if self.date and self.date > timezone.localdate():
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


class OfficeLocation(models.Model):
    """
    Where self check-in is accepted. One row, edited by HR on the "Check-in location" page.
    A check-in passes when it comes from an office IP address or from within the radius
    (or both, when require_both is on); otherwise it goes to Attendance Review.
    """
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    radius_m = models.PositiveIntegerField(default=150, help_text='How far from the office a check-in may be, in metres.')
    allowed_ips = models.TextField(blank=True, help_text="Office internet IP addresses, one per line.")
    require_both = models.BooleanField(
        default=False, help_text='Require office Wi-Fi AND location. Leave off unless the office has a static IP.')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Office check-in location'

    def __str__(self):
        return 'Office check-in location'

    @classmethod
    def current(cls):
        return cls.objects.order_by('pk').first()

    @property
    def ip_list(self):
        return [line.strip() for line in self.allowed_ips.replace(',', '\n').splitlines() if line.strip()]

    @property
    def has_gps(self):
        return self.latitude is not None and self.longitude is not None

    @property
    def is_configured(self):
        return self.has_gps or bool(self.ip_list)

    def evaluate(self, ip, latitude=None, longitude=None, accuracy=None):
        """Returns (ok, reason, distance_m)."""
        on_wifi = bool(ip) and ip in self.ip_list
        distance = None
        in_radius = False
        if self.has_gps and latitude is not None and longitude is not None:
            distance = round(distance_m(float(self.latitude), float(self.longitude), latitude, longitude))
            # Phones report how sure they are; allow for that, but never more than 100 m of slack.
            in_radius = distance - min(accuracy or 0, 100) <= self.radius_m

        checks = []
        if self.ip_list:
            checks.append(on_wifi)
        if self.has_gps:
            checks.append(in_radius)
        ok = all(checks) if self.require_both else any(checks)

        if ok:
            return True, '', distance
        reasons = []
        if self.ip_list and not on_wifi:
            reasons.append('not on office Wi-Fi')
        if self.has_gps:
            if distance is None:
                reasons.append('location not shared')
            elif not in_radius:
                reasons.append(f'{format_distance(distance)} from the office')
        return False, ', '.join(reasons), distance


def distance_m(lat1, lng1, lat2, lng2):
    """Great-circle distance in metres (haversine)."""
    import math
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def format_distance(metres):
    return f'{metres / 1000:.1f} km' if metres >= 1000 else f'{metres} m'


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
    # Where a self check-in came from, kept for review.
    check_in_ip = models.CharField(max_length=45, blank=True)
    check_in_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_in_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    check_in_accuracy_m = models.PositiveIntegerField(null=True, blank=True)
    check_in_distance_m = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ['-date']
        unique_together = ('employee', 'date')
        verbose_name_plural = 'Daily attendance'

    def save(self, *args, **kwargs):
        # One rule for self check-in, imports and admin edits alike.
        self.is_late = is_late_check_in(self.check_in_time) if self.status == 'present' else False
        update_fields = kwargs.get('update_fields')
        if update_fields is not None and 'is_late' not in update_fields:
            kwargs['update_fields'] = [*update_fields, 'is_late']
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.employee.name} - {self.date} - {self.status}"


class LeaveRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_requests')
    date = models.DateField()
    reason = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    requested_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(blank=True, null=True)
    decided_by = models.CharField(max_length=150, blank=True)
    decision_note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-requested_at']
        constraints = [
            models.UniqueConstraint(
                fields=['employee', 'date'], condition=models.Q(status='pending'),
                name='one_pending_leave_request_per_day',
            ),
        ]

    def __str__(self):
        return f"{self.employee.name} - {self.date} - {self.status}"