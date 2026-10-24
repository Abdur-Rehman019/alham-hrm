from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy
from . import two_factor, views

urlpatterns = [
    path('login/', auth_views.LoginView.as_view(template_name='core/login.html', redirect_authenticated_user=True), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('post-login/', views.post_login_redirect, name='post_login_redirect'),
    path('change-password/', views.change_password, name='change_password'),
    path('two-factor/setup/', two_factor.setup, name='two_factor_setup'),
    path('two-factor/verify/', two_factor.verify, name='two_factor_verify'),
    path('two-factor/', two_factor.manage, name='two_factor_manage'),
    path('audit-log/', views.audit_log, name='audit_log'),

    path('password-reset/', views.PasswordResetView.as_view(), name='password_reset'),
    path('password-reset/done/', auth_views.PasswordResetDoneView.as_view(
        template_name='core/password_reset_done.html'
    ), name='password_reset_done'),
    path('reset/<uidb64>/<token>/', views.PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('reset/done/', views.PasswordResetCompleteView.as_view(), name='password_reset_complete'),
]