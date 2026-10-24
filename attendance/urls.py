from django.urls import path
from . import employee_portal, views

urlpatterns = [
    path('', views.leave_list, name='leave_list'),
    path('add/', views.leave_add, name='leave_add'),
    path('<int:pk>/delete/', views.leave_delete, name='leave_delete'),
    path('holiday/', views.holiday_add, name='holiday_add'),
    path('check-in-location/', views.office_location, name='office_location'),
    path('portal/', employee_portal.portal_dashboard, name='portal_dashboard'),
    path('portal/attendance/', employee_portal.portal_attendance, name='portal_attendance'),
    path('portal/leaves/', employee_portal.portal_leaves, name='portal_leaves'),
    path('portal/enrollments/', employee_portal.portal_enrollments, name='portal_enrollments'),
    path('portal/salary/', employee_portal.portal_salary, name='portal_salary'),
    path('my-leave-requests/<int:pk>/cancel/', employee_portal.leave_request_cancel, name='leave_request_cancel'),
    path('leave-requests/', views.leave_requests_list, name='leave_requests_list'),
    path('leave-requests/<int:pk>/approve/', views.leave_request_approve, name='leave_request_approve'),
    path('leave-requests/<int:pk>/reject/', views.leave_request_reject, name='leave_request_reject'),
]