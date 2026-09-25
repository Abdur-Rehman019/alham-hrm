from django import forms
from .models import IncentiveRule, StudentEnrollment


class IncentiveRuleForm(forms.ModelForm):
    class Meta:
        model = IncentiveRule
        fields = ['destination_country', 'amount']
        widgets = {
            'destination_country': forms.TextInput(attrs={'class': 'form-control'}),
            'amount': forms.NumberInput(attrs={'class': 'form-control'}),
        }


class StudentEnrollmentForm(forms.ModelForm):
    class Meta:
        model = StudentEnrollment
        fields = ['student_name', 'destination_country', 'counselor', 'confirmed_on', 'incentive_paid']
        widgets = {
            'student_name': forms.TextInput(attrs={'class': 'form-control'}),
            'destination_country': forms.TextInput(attrs={'class': 'form-control', 'list': 'country-list'}),
            'counselor': forms.Select(attrs={'class': 'form-select'}),
            'confirmed_on': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'incentive_paid': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
