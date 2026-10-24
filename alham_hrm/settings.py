"""
Django settings for alham_hrm project.
"""

import datetime
import sys
from pathlib import Path
from decouple import config, Csv
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='127.0.0.1,localhost', cast=Csv())
# Railway provides its public domain, and its health checks arrive with this host name.
RAILWAY_PUBLIC_DOMAIN = config('RAILWAY_PUBLIC_DOMAIN', default='')
for _host in (RAILWAY_PUBLIC_DOMAIN, 'healthcheck.railway.app'):
    if _host and _host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_host)

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'axes',
    'django_otp',
    'django_otp.plugins.otp_totp',
    'django_otp.plugins.otp_static',
    'core',
    'employees',
    'attendance',
    'payroll',
    'dashboard',
    'imports',
]

AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'core.backends.EmailOrUsernameBackend',  # username or company email
]

# Admin and staff accounts must confirm each sign-in with an authenticator app code (or a backup code).
ADMIN_2FA_REQUIRED = config('ADMIN_2FA_REQUIRED', default=True, cast=bool)
OTP_TOTP_ISSUER = 'ALHAM HRM'

AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1
AXES_LOCKOUT_PARAMETERS = [['username', 'ip_address']]
AXES_RESET_COOL_OFF_ON_FAILURE_DURING_LOCKOUT = False
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = 'core/locked_out.html'
# Behind Railway's proxy every request comes from the proxy, so read the real client IP.
AXES_CLIENT_IP_CALLABLE = 'core.middleware.client_ip'

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django_otp.middleware.OTPMiddleware',
    'core.audit.AuditMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'core.middleware.RoleAccessMiddleware',
    'axes.middleware.AxesMiddleware',
]

ROOT_URLCONF = 'alham_hrm.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.admin_counts',
            ],
        },
    },
]

WSGI_APPLICATION = 'alham_hrm.wsgi.application'

DATABASES = {
    'default': dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# Office hours 10:00-18:00 with a 15-minute margin: a check-in at 10:15 is on time, 10:16 is late.
# No self check-ins are accepted after OFFICE_END.
OFFICE_START = datetime.time.fromisoformat(config('OFFICE_START', default='10:00'))
OFFICE_END = datetime.time.fromisoformat(config('OFFICE_END', default='18:00'))
# Self check-in opens here (stops a "check-in" at midnight counting as an early arrival).
CHECK_IN_OPENS = datetime.time.fromisoformat(config('CHECK_IN_OPENS', default='08:00'))
LATE_GRACE_MINUTES = config('LATE_GRACE_MINUTES', default=15, cast=int)

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Karachi'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'whitenoise.storage.CompressedStaticFilesStorage'},
}
MEDIA_URL = 'media/'
# On Railway, mount a volume and point MEDIA_ROOT at it, or uploaded photos vanish on each deploy.
MEDIA_ROOT = Path(config('MEDIA_ROOT', default=str(BASE_DIR / 'media')))
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'post_login_redirect'
LOGOUT_REDIRECT_URL = 'login'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

if not DEBUG:
    SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    CSRF_TRUSTED_ORIGINS = [f'https://{host}' for host in ALLOWED_HOSTS if host not in ('127.0.0.1', 'localhost')]
    SECURE_REFERRER_POLICY = 'same-origin'
    # Health checks come over plain HTTP from inside Railway; do not redirect them.
    SECURE_REDIRECT_EXEMPT = [r'^healthz/$']

SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_AGE = 1800
SESSION_SAVE_EVERY_REQUEST = True

# Railway blocks SMTP on Free/Trial/Hobby plans, so BREVO_API_KEY (HTTPS API) is the preferred setup.
BREVO_API_KEY = config('BREVO_API_KEY', default='')
EMAIL_HOST = config('EMAIL_HOST', default='')
EMAIL_BACKEND = config(
    'EMAIL_BACKEND',
    default=(
        'core.email.BrevoEmailBackend' if BREVO_API_KEY else
        'django.core.mail.backends.smtp.EmailBackend' if EMAIL_HOST else
        'django.core.mail.backends.console.EmailBackend'
    ),
)
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_TIMEOUT = config('EMAIL_TIMEOUT', default=10, cast=int)
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default='ALHAM HRM <noreply@alham.pk>')
SERVER_EMAIL = DEFAULT_FROM_EMAIL
PASSWORD_RESET_TIMEOUT = 60 * 60 * 24  # reset links work for one day

# Errors go to stdout so they show up in Railway's deploy logs.
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'plain': {'format': '%(levelname)s %(name)s: %(message)s'}},
    'handlers': {'console': {'class': 'logging.StreamHandler', 'formatter': 'plain'}},
    'root': {'handlers': ['console'], 'level': 'INFO'},
    'loggers': {
        'django': {'handlers': ['console'], 'level': 'INFO', 'propagate': False},
        'django.request': {'handlers': ['console'], 'level': 'ERROR', 'propagate': False},
        'axes': {'handlers': ['console'], 'level': 'WARNING', 'propagate': False},
    },
}

CACHES = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}

# Password hashing is deliberately slow; tests do not need that and run far faster without it.
if len(sys.argv) > 1 and sys.argv[1] == 'test':
    PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']
    # Most tests sign admins in directly; the two-factor tests switch this back on.
    ADMIN_2FA_REQUIRED = False