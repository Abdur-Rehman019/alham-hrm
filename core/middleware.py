from django.shortcuts import redirect
from django.contrib import messages

COUNSELOR_ALLOWED_URL_NAMES = {
    'post_login_redirect',
    'self_attendance',
    'logout',
    'password_reset',
    'password_reset_done',
    'password_reset_confirm',
    'password_reset_complete',
}


def is_admin_user(user):
    return user.is_authenticated and (user.is_superuser or user.is_staff)


class RoleAccessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        user = request.user
        if user.is_authenticated and not is_admin_user(user):
            url_name = request.resolver_match.url_name if request.resolver_match else None
            if url_name not in COUNSELOR_ALLOWED_URL_NAMES and not request.path.startswith('/static/') and not request.path.startswith('/media/'):
                messages.info(request, "Your account only has access to attendance check-in.")
                return redirect('self_attendance')
        return None