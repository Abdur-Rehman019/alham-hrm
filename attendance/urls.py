from django.urls import path
from . import views

urlpatterns = [
    path('', views.leave_list, name='leave_list'),
    path('add/', views.leave_add, name='leave_add'),
    path('<int:pk>/delete/', views.leave_delete, name='leave_delete'),
    path('holiday/', views.holiday_add, name='holiday_add'),
    path('my-attendance/', views.self_attendance, name='self_attendance'),
    path('my-payslip/<int:pk>/', views.my_payslip_pdf, name='my_payslip_pdf'),
    path('my-leave-requests/<int:pk>/cancel/', views.leave_request_cancel, name='leave_request_cancel'),
    path('leave-requests/', views.leave_requests_list, name='leave_requests_list'),
    path('leave-requests/<int:pk>/approve/', views.leave_request_approve, name='leave_request_approve'),
    path('leave-requests/<int:pk>/reject/', views.leave_request_reject, name='leave_request_reject'),
]