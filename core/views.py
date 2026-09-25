# Auth views are handled directly in core/urls.py using Django's built-in LoginView/LogoutView.
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from .middleware import is_admin_user


@login_required
def post_login_redirect(request):
    """Sends admins to the full dashboard, and employee accounts to their
    own self-service attendance check-in page."""
    if is_admin_user(request.user):
        return redirect('dashboard_home')
    return redirect('self_attendance')