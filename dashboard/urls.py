from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard_home, name='dashboard_home'),
    path('certificate/<int:employee_id>/<int:year>/<int:month>/', views.counselor_of_month_certificate, name='counselor_of_month_certificate'),
]