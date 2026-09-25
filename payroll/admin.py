from django.contrib import admin
from .models import IncentiveRule, StudentEnrollment, Payroll

admin.site.register(IncentiveRule)
admin.site.register(StudentEnrollment)
admin.site.register(Payroll)
