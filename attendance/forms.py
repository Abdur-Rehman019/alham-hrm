import datetime

from django import forms
from django.utils import timezone

from .models import DailyAttendance, Leave, LeaveRequest, OfficeLocation


class OfficeLocationForm(forms.ModelForm):
    class Meta:
        model = OfficeLocation
        fields = ['latitude', 'longitude', 'radius_m', 'allowed_ips', 'require_both']
        labels = {'radius_m': 'Allowed distance (metres)', 'allowed_ips': 'Office internet IP addresses',
                  'require_both': 'Require office Wi-Fi and location together'}
        widgets = {
            'latitude': forms.NumberInput(attrs={'class': 'form-control', 'step': 'any', 'placeholder': 'e.g. 31.520370'}),
            'longitude': forms.NumberInput(attrs={'class': 'form-control', 'step': 'any', 'placeholder': 'e.g. 74.358749'}),
            'radius_m': forms.NumberInput(attrs={'class': 'form-control', 'min': 30, 'max': 2000}),
            'allowed_ips': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'One per line'}),
            'require_both': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

    def clean_latitude(self):
        value = self.cleaned_data.get('latitude')
        if value is not None and not -90 <= value <= 90:
            raise forms.ValidationError('Latitude must be between -90 and 90.')
        return value

    def clean_longitude(self):
        value = self.cleaned_data.get('longitude')
        if value is not None and not -180 <= value <= 180:
            raise forms.ValidationError('Longitude must be between -180 and 180.')
        return value

    def clean_radius_m(self):
        value = self.cleaned_data['radius_m']
        if not 30 <= value <= 2000:
            raise forms.ValidationError('Use a distance between 30 and 2000 metres.')
        return value

    def clean_allowed_ips(self):
        import ipaddress
        lines = [line.strip() for line in self.cleaned_data['allowed_ips'].replace(',', '\n').splitlines() if line.strip()]
        for line in lines:
            try:
                ipaddress.ip_address(line)
            except ValueError:
                raise forms.ValidationError(f'"{line}" is not a valid IP address.')
        return '\n'.join(dict.fromkeys(lines))

    def clean(self):
        cleaned = super().clean()
        if (cleaned.get('latitude') is None) != (cleaned.get('longitude') is None):
            raise forms.ValidationError('Enter both latitude and longitude, or leave both empty.')
        return cleaned


class LeaveForm(forms.ModelForm):
    class Meta:
        model = Leave
        fields = ['employee', 'date', 'leave_type', 'reason']
        widgets = {
            'employee': forms.Select(attrs={'class': 'form-select'}),
            'date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'leave_type': forms.Select(attrs={'class': 'form-select'}),
            'reason': forms.TextInput(attrs={'class': 'form-control'}),
        }


class LeaveRequestForm(forms.Form):
    date = forms.DateField(widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}))
    reason = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={'class': 'form-control', 'minlength': 3}),
    )

    def __init__(self, *args, employee, **kwargs):
        self.employee = employee
        super().__init__(*args, **kwargs)

    def clean_reason(self):
        reason = self.cleaned_data['reason'].strip()
        if len(reason) < 3:
            raise forms.ValidationError('Please give a short reason for the leave.')
        return reason

    def clean_date(self):
        day = self.cleaned_data['date']
        today = timezone.localdate()
        if day < today:
            raise forms.ValidationError('You cannot request leave for a past date.')
        if day > today + datetime.timedelta(days=60):
            raise forms.ValidationError('Leave can be requested up to 60 days ahead.')
        if day.weekday() == 6:
            raise forms.ValidationError('Sunday is already a holiday.')
        if day < self.employee.joined_on:
            raise forms.ValidationError('That date is before your joining date.')
        if LeaveRequest.objects.filter(employee=self.employee, date=day, status='pending').exists():
            raise forms.ValidationError('You already have a pending request for that date.')
        if Leave.objects.filter(employee=self.employee, date=day).exists() or \
                LeaveRequest.objects.filter(employee=self.employee, date=day, status='approved').exists():
            raise forms.ValidationError('You already have approved leave on that date.')
        if DailyAttendance.objects.filter(employee=self.employee, date=day).exists():
            raise forms.ValidationError('Your attendance for that date is already recorded.')
        return day
