from django import forms
from .models import Leave


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
