from django.urls import path
from . import views

urlpatterns = [
    path('', views.employee_list, name='employee_list'),
    path('add/', views.employee_add, name='employee_add'),
    path('<int:pk>/', views.employee_detail, name='employee_detail'),
    path('<int:pk>/edit/', views.employee_edit, name='employee_edit'),
    path('<int:pk>/deactivate/', views.employee_deactivate, name='employee_deactivate'),
    path('<int:pk>/create-login/', views.employee_create_login, name='employee_create_login'),
    path('<int:pk>/remove-login/', views.employee_remove_login, name='employee_remove_login'),
    path('<int:pk>/terminate/', views.employee_terminate, name='employee_terminate'),
]
