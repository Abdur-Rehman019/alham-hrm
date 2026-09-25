from django.contrib import admin
from .models import Employee


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('employee_id', 'name', 'role', 'monthly_salary', 'is_active')
    search_fields = ('name', 'employee_id', 'email')
    list_filter = ('role', 'is_active')
