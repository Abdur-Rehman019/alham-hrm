from django.contrib import admin
from .models import Leave


@admin.register(Leave)
class LeaveAdmin(admin.ModelAdmin):
    list_display = ('employee', 'date', 'leave_type', 'is_deducted')
    list_filter = ('leave_type', 'is_deducted')
    search_fields = ('employee__name',)
