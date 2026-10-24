from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """Read-only: an audit trail that can be edited is not an audit trail."""
    list_display = ('created_at', 'actor_name', 'action', 'category', 'object_repr', 'ip_address')
    list_filter = ('category', 'action')
    search_fields = ('actor_name', 'object_repr', 'note')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
