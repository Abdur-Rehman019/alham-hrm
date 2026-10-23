from django.conf import settings
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import path, include, re_path
from django.views.static import serve

from core.views import healthz

handler404 = 'core.views.page_not_found'
handler500 = 'core.views.server_error'

urlpatterns = [
    path('healthz/', healthz, name='healthz'),
    path('admin/', admin.site.urls),
    path('', include('dashboard.urls')),
    path('accounts/', include('core.urls')),
    path('employees/', include('employees.urls')),
    path('attendance/', include('attendance.urls')),
    path('payroll/', include('payroll.urls')),
    path('imports/', include('imports.urls')),
    # Employee photos, for signed-in users only (Django does not serve media itself when DEBUG is off).
    re_path(r'^media/(?P<path>employee_photos/.*)$', login_required(serve), {'document_root': settings.MEDIA_ROOT}),
]
