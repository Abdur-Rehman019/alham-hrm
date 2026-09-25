from django.urls import path
from . import views

urlpatterns = [
    path('', views.leave_list, name='leave_list'),
    path('add/', views.leave_add, name='leave_add'),
    path('<int:pk>/delete/', views.leave_delete, name='leave_delete'),
    path('my-attendance/', views.self_attendance, name='self_attendance'),
]