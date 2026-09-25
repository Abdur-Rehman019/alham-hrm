from django.urls import path
from . import views

urlpatterns = [
    path('enrollments/', views.enrollment_import, name='enrollment_import'),
    path('enrollments/confirm/', views.enrollment_import_confirm, name='enrollment_import_confirm'),
    path('attendance/', views.attendance_import, name='attendance_import'),
    path('attendance/review/', views.attendance_review, name='attendance_review'),
    path('attendance/review/<int:pk>/resolve/', views.attendance_resolve, name='attendance_resolve'),
]