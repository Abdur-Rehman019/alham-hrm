import datetime

from django import forms
from django.utils import timezone

from .models import DailyAttendance, Leave, LeaveRequest


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
