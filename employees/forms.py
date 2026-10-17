from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from .models import Employee


class EmployeeForm(forms.ModelForm):
    class Meta:
        model = Employee
        fields = ['name', 'cnic', 'date_of_birth', 'role', 'monthly_salary', 'phone',
                  'email', 'address', 'joined_on', 'leaving_date', 'is_active', 'photo']
        widgets = {
            'joined_on': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'leaving_date': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'date_of_birth': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'cnic': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '12345-1234567-1'}),
            'role': forms.Select(attrs={'class': 'form-select'}),
            'monthly_salary': forms.NumberInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'photo': forms.ClearableFileInput(attrs={'class': 'form-control'}),
        }

    def clean(self):
        cleaned = super().clean()
        # Ticking "Is active" means the person is (back) at work, so any old leaving date is dropped.
        if cleaned.get('is_active') and cleaned.get('leaving_date'):
            cleaned['leaving_date'] = None
        return cleaned


class CreateLoginForm(forms.Form):
    username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={'class': 'form-control'}))
    email = forms.EmailField(
        required=False,
        help_text='Needed if this person should be able to use "Forgot password".',
        widget=forms.EmailInput(attrs={'class': 'form-control'}),
    )
    password1 = forms.CharField(label='Temporary password', widget=forms.PasswordInput(attrs={'class': 'form-control'}))
    password2 = forms.CharField(label='Confirm temporary password', widget=forms.PasswordInput(attrs={'class': 'form-control'}))

    def clean_username(self):
        username = self.cleaned_data['username'].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError('That username is already taken.')
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip()
        if email and User.objects.filter(email__iexact=email).exists():
            raise ValidationError('Another account already uses this email.')
        return email

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get('password1'), cleaned.get('password2')
        if p1 and p2:
            if p1 != p2:
                raise ValidationError('Passwords do not match.')
            password_validation.validate_password(p1)
        return cleaned