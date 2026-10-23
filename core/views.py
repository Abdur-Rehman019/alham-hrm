from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render

from employees.models import Employee
from .middleware import is_admin_user


@login_required
def post_login_redirect(request):
    """Admins go to the dashboard, employees to their own portal."""
    if is_admin_user(request.user):
        return redirect('dashboard_home')
    return redirect('portal_dashboard')


class StrictPasswordChangeForm(PasswordChangeForm):
    def clean_new_password1(self):
        new = self.cleaned_data.get('new_password1')
        old = self.cleaned_data.get('old_password')
        if new and old and new == old:
            raise ValidationError('Your new password must be different from the current one.')
        return new


@login_required
def change_password(request):
    profile = getattr(request.user, 'employee_profile', None)
    forced = bool(profile and profile.must_change_password)
    form = StrictPasswordChangeForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)  # stay signed in after the change
        Employee.objects.filter(user=user).update(must_change_password=False)
        messages.success(request, 'Your password has been changed.')
        return redirect('post_login_redirect')
    for field in form.fields.values():
        field.widget.attrs['class'] = 'form-control'
    return render(request, 'core/change_password.html', {'form': form, 'forced': forced})