import logging

from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import connection
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse_lazy

from employees.models import Employee
from .email import email_problem
from .forms import EmployeePasswordResetForm
from .middleware import client_ip, is_admin_user
from .models import AuditLog

logger = logging.getLogger(__name__)
RESET_REQUESTS_PER_HOUR = 5


def healthz(request):
    """Used by Railway's health check: the app is up and the database answers."""
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
    except Exception:
        logger.exception('Health check: database unavailable')
        return JsonResponse({'status': 'database unavailable'}, status=503)
    return JsonResponse({'status': 'ok'})


class PasswordResetView(auth_views.PasswordResetView):
    template_name = 'core/password_reset.html'
    email_template_name = 'core/password_reset_email.html'
    subject_template_name = 'core/password_reset_subject.txt'
    form_class = EmployeePasswordResetForm
    success_url = reverse_lazy('password_reset_done')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['email_problem'] = email_problem()
        return context

    def form_valid(self, form):
        problem = email_problem()
        if problem:
            logger.error('Password reset requested but %s', problem)
            form.add_error(None, 'Password reset by email is not available yet. Please ask HR to reset your password.')
            return self.form_invalid(form)

        key = f'password-reset:{client_ip(self.request)}'
        attempts = cache.get(key, 0)
        if attempts >= RESET_REQUESTS_PER_HOUR:
            form.add_error(None, 'Too many reset requests. Please wait an hour and try again.')
            return self.form_invalid(form)
        cache.set(key, attempts + 1, 60 * 60)

        try:
            return super().form_valid(form)
        except Exception:
            logger.exception('Password reset email could not be sent')
            form.add_error(None, 'We could not send the email right now. Please try again later or ask HR to reset your password.')
            return self.form_invalid(form)


@login_required
def audit_log(request):
    """Read-only history of employee, salary, payroll, incentive and login changes."""
    if not is_admin_user(request.user):
        return redirect('post_login_redirect')
    entries = AuditLog.objects.select_related('actor')
    category = request.GET.get('category', '')
    if category in dict(AuditLog.CATEGORY_CHOICES):
        entries = entries.filter(category=category)
    query = request.GET.get('q', '').strip()
    if query:
        entries = entries.filter(Q(object_repr__icontains=query) | Q(actor_name__icontains=query) | Q(note__icontains=query))
    page = Paginator(entries, 50).get_page(request.GET.get('page'))
    return render(request, 'core/audit_log.html', {
        'page': page, 'category': category, 'query': query, 'categories': AuditLog.CATEGORY_CHOICES,
    })


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = 'core/password_reset_confirm.html'
    success_url = reverse_lazy('password_reset_complete')

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for field in form.fields.values():
            field.widget.attrs['class'] = 'form-control'
        return form

    def form_valid(self, form):
        response = super().form_valid(form)
        user = form.user
        # A new password chosen through the emailed link is the user's own, and ends any lockout.
        Employee.objects.filter(user=user).update(must_change_password=False)
        from axes.utils import reset
        reset(username=user.get_username())
        # Several accounts can share one email; say exactly which one was changed.
        self.request.session['reset_username'] = user.get_username()
        return response


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = 'core/password_reset_complete.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['reset_username'] = self.request.session.pop('reset_username', '')
        return context


def page_not_found(request, exception):
    return render(request, 'core/error.html', {
        'code': 404, 'title': 'Page not found',
        'text': "The page you are looking for doesn't exist or has moved.",
    }, status=404)


def server_error(request):
    # Rendered without the request context: the error may have come from the database or a context processor.
    from django.template.loader import render_to_string
    return HttpResponse(render_to_string('core/error.html', {
        'code': 500, 'title': 'Something went wrong',
        'text': 'The error has been logged. Please go back and try again in a moment.',
    }), status=500)


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