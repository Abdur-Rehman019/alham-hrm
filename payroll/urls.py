from django.urls import path
from . import views

urlpatterns = [
    path('incentive-rules/', views.incentive_rule_list, name='incentive_rule_list'),
    path('incentive-rules/<int:pk>/delete/', views.incentive_rule_delete, name='incentive_rule_delete'),
    path('enrollments/', views.enrollment_list, name='enrollment_list'),
    path('enrollments/add/', views.enrollment_add, name='enrollment_add'),
    path('generate/', views.payroll_generate, name='payroll_generate'),
    path('payslip/<int:pk>/', views.payslip_pdf, name='payslip_pdf'),
    path('payslip/<int:pk>/approve/', views.payroll_approve, name='payroll_approve'),
    path('payslip/<int:pk>/email/', views.payslip_email_send, name='payslip_email_send'),
]