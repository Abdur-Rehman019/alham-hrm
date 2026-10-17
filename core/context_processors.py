def admin_counts(request):
    """Pending leave-request badge for the admin sidebar."""
    user = request.user
    if user.is_authenticated and (user.is_staff or user.is_superuser):
        from attendance.models import LeaveRequest
        return {'pending_leave_count': LeaveRequest.objects.filter(status='pending').count()}
    return {}