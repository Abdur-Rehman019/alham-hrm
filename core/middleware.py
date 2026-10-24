from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.urls import reverse

# Everything an employee (non-admin) account may reach. All other pages redirect back to the portal.
COUNSELOR_ALLOWED_URL_NAMES = {
    'post_login_redirect', 'portal_dashboard', 'portal_attendance', 'portal_leaves',
    'portal_enrollments', 'portal_salary', 'leave_request_cancel',
    'change_password', 'logout',
    'password_reset', 'password_reset_done', 'password_reset_confirm', 'password_reset_complete',
}
# While a temporary password is still in use, only these are reachable.
FORCED_CHANGE_ALLOWED_URL_NAMES = {'change_password', 'logout'}
# Until an admin has entered their authenticator code this session, only these are reachable.
TWO_FACTOR_ALLOWED_URL_NAMES = {'two_factor_setup', 'two_factor_verify', 'logout'}


def client_ip(request):
    """
    The visitor's real IP behind Railway's proxy. The proxy appends the address it saw to
    X-Forwarded-For, so the last entry is trustworthy; earlier entries can be typed by the visitor.
    """
    forwarded = [part.strip() for part in request.META.get('HTTP_X_FORWARDED_FOR', '').split(',') if part.strip()]
    return forwarded[-1] if forwarded else request.META.get('REMOTE_ADDR', '')


def is_admin_user(user):
    return user.is_authenticated and (user.is_superuser or user.is_staff)


class RoleAccessMiddleware:
    """
    1. An admin/staff account must enter its authenticator code (or set one up) before anything else.
    2. A user still on a temporary password is sent to the change-password page.
    3. Employee accounts can only reach their own portal pages.
    Admin/staff accounts are never restricted by rule 3.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = request.user
        if not user.is_authenticated:
            return None
        if request.path.startswith(('/static/', '/media/')):
            return None
        url_name = request.resolver_match.url_name if request.resolver_match else None

        if (is_admin_user(user) and settings.ADMIN_2FA_REQUIRED and not user.is_verified()
                and url_name not in TWO_FACTOR_ALLOWED_URL_NAMES):
            from .two_factor import has_two_factor
            target = 'two_factor_verify' if has_two_factor(user) else 'two_factor_setup'
            next_path = request.get_full_path()
            if url_name in (None, 'post_login_redirect') or request.method != 'GET':
                return redirect(target)
            return redirect(f"{reverse(target)}?{urlencode({'next': next_path})}")

        profile = getattr(user, 'employee_profile', None)
        if profile is not None and profile.must_change_password and url_name not in FORCED_CHANGE_ALLOWED_URL_NAMES:
            messages.warning(request, "For your security, please set a new password before continuing.")
            return redirect('change_password')

        if not is_admin_user(user) and url_name not in COUNSELOR_ALLOWED_URL_NAMES:
            messages.info(request, "Your account only has access to your own employee portal.")
            return redirect('portal_dashboard')
        return None