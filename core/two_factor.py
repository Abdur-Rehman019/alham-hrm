"""
Two-factor sign-in for admin and staff accounts: an authenticator app code (TOTP) on every sign-in,
with one-time backup codes for a lost phone.
"""
import base64
import datetime
import hashlib
import secrets

import qrcode
import qrcode.image.svg
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods
from django_otp import login as otp_login
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from . import audit
from .middleware import is_admin_user
from .models import TrustedDevice

BACKUP_CODE_COUNT = 10
TRUSTED_COOKIE = 'hrm_trusted_device'
TRUSTED_DAYS = 30


def _token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def remember_this_computer(request, response):
    """Called after a correct code when "Remember this computer" was ticked."""
    token = secrets.token_urlsafe(32)
    expires = timezone.now() + datetime.timedelta(days=TRUSTED_DAYS)
    TrustedDevice.objects.create(
        user=request.user, token_hash=_token_hash(token), auth_hash=request.user.get_session_auth_hash(),
        description=request.META.get('HTTP_USER_AGENT', '')[:200], expires_at=expires,
    )
    response.set_cookie(
        TRUSTED_COOKIE, token, max_age=TRUSTED_DAYS * 24 * 3600, httponly=True,
        secure=not settings.DEBUG, samesite='Lax',
    )


def trust_from_cookie(request):
    """If this computer is remembered for this user, mark the session as verified. Returns True if so."""
    token = request.COOKIES.get(TRUSTED_COOKIE)
    if not token:
        return False
    trusted = TrustedDevice.objects.filter(
        token_hash=_token_hash(token), user=request.user, expires_at__gt=timezone.now()).first()
    # A password change alters the auth hash, so computers remembered before it no longer count.
    if trusted is None or not constant_time_compare(trusted.auth_hash, request.user.get_session_auth_hash()):
        return False
    device = TOTPDevice.objects.filter(user=request.user, confirmed=True).first()
    if device is None:
        return False
    otp_login(request, device)
    TrustedDevice.objects.filter(pk=trusted.pk).update(last_used_at=timezone.now())
    return True


def forget_this_computer(request):
    token = request.COOKIES.get(TRUSTED_COOKIE)
    if token:
        TrustedDevice.objects.filter(token_hash=_token_hash(token)).delete()


def _on_logout(sender, request, user, **kwargs):
    # Signing out on purpose means "don't trust this computer any more" (e.g. a shared PC).
    if request is not None:
        forget_this_computer(request)


def _on_authenticator_removed(sender, instance, **kwargs):
    TrustedDevice.objects.filter(user_id=instance.user_id).delete()


def connect_signals():
    from django.contrib.auth.signals import user_logged_out
    from django.db.models.signals import post_delete
    user_logged_out.connect(_on_logout, dispatch_uid='two-factor-forget-on-logout')
    post_delete.connect(_on_authenticator_removed, sender=TOTPDevice, dispatch_uid='two-factor-forget-on-reset')


def has_two_factor(user):
    return TOTPDevice.objects.filter(user=user, confirmed=True).exists()


def _clean(code):
    return ''.join((code or '').split()).replace('-', '').lower()


def _next_url(request):
    target = request.POST.get('next') or request.GET.get('next') or ''
    if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return target
    return 'post_login_redirect'


def _new_backup_codes(user):
    device, _ = StaticDevice.objects.get_or_create(user=user, name='Backup codes', defaults={'confirmed': True})
    device.token_set.all().delete()
    codes = [StaticToken.random_token() for _ in range(BACKUP_CODE_COUNT)]
    StaticToken.objects.bulk_create([StaticToken(device=device, token=code) for code in codes])
    return codes


@login_required
@require_http_methods(['GET', 'POST'])
def setup(request):
    """First sign-in after 2FA is switched on: link an authenticator app."""
    if not is_admin_user(request.user):
        return redirect('post_login_redirect')
    if has_two_factor(request.user):
        return redirect('two_factor_verify')

    device = TOTPDevice.objects.filter(user=request.user, confirmed=False).first()
    if device is None:
        device = TOTPDevice.objects.create(user=request.user, name='Authenticator app', confirmed=False)

    error = None
    if request.method == 'POST':
        code = _clean(request.POST.get('code'))
        if code.isdigit() and device.verify_token(code):
            with transaction.atomic():
                device.confirmed = True
                device.save(update_fields=['confirmed'])
                TOTPDevice.objects.filter(user=request.user, confirmed=False).delete()
                codes = _new_backup_codes(request.user)
            otp_login(request, device)
            audit.record(request.user, 'security', note='Two-factor sign-in turned on')
            response = render(request, 'core/two_factor_backup_codes.html', {'codes': codes, 'first_time': True})
            if request.POST.get('remember'):
                remember_this_computer(request, response)
            return response
        error = "That code didn't match. Check the time on your phone is set automatically, then try the newest code."

    qr_svg = qrcode.make(device.config_url, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    # For apps where the QR code cannot be scanned, the same secret typed in by hand.
    manual_key = base64.b32encode(device.bin_key).decode().rstrip('=')
    return render(request, 'core/two_factor_setup.html', {
        'qr_svg': qr_svg.to_string(encoding='unicode'),
        'manual_key': ' '.join(manual_key[i:i + 4] for i in range(0, len(manual_key), 4)),
        'error': error,
    })


@login_required
@require_http_methods(['GET', 'POST'])
def verify(request):
    """Every admin sign-in: enter the current 6-digit code, or one backup code."""
    if not is_admin_user(request.user):
        return redirect('post_login_redirect')
    if not has_two_factor(request.user):
        return redirect('two_factor_setup')
    if request.user.is_verified():
        return redirect(_next_url(request))

    error = None
    if request.method == 'POST':
        code = _clean(request.POST.get('code'))
        if code.isdigit() and len(code) == 6:
            devices = TOTPDevice.objects.filter(user=request.user, confirmed=True)
        else:
            devices = StaticDevice.objects.filter(user=request.user, confirmed=True)
        devices = list(devices)
        throttled = bool(devices) and not any(d.verify_is_allowed()[0] for d in devices)
        device = None if throttled else next((d for d in devices if d.verify_token(code)), None)
        if device is not None:
            otp_login(request, device)
            if isinstance(device, StaticDevice):
                left = device.token_set.count()
                audit.record(request.user, 'security', note=f'Signed in with a backup code ({left} left)')
                messages.warning(request, f"You signed in with a backup code. {left} backup code{'s' if left != 1 else ''} left; "
                                          "create new ones under Two-factor security if you are running low.")
            response = redirect(_next_url(request))
            if request.POST.get('remember'):
                remember_this_computer(request, response)
                audit.record(request.user, 'security', note=f'Computer remembered for {TRUSTED_DAYS} days')
            return response
        error = ('Too many wrong codes. Wait a little before trying again.' if throttled
                 else "That code didn't work. Use the newest 6-digit code from your authenticator app, or a backup code.")
    return render(request, 'core/two_factor_verify.html', {'error': error, 'next': request.GET.get('next', '')})


@login_required
@require_http_methods(['GET', 'POST'])
def manage(request):
    """Status page: replace backup codes. Reached only after a verified sign-in (see RoleAccessMiddleware)."""
    if not is_admin_user(request.user):
        return redirect('post_login_redirect')
    if request.method == 'POST' and request.POST.get('action') == 'backup_codes':
        codes = _new_backup_codes(request.user)
        audit.record(request.user, 'security', note='New backup codes created')
        return render(request, 'core/two_factor_backup_codes.html', {'codes': codes, 'first_time': False})
    if request.method == 'POST' and request.POST.get('action') == 'forget_all':
        count, _ = TrustedDevice.objects.filter(user=request.user).delete()
        audit.record(request.user, 'security', note=f'Forgot {count} remembered computer(s)')
        messages.success(request, 'All remembered computers were forgotten. Each will ask for a code at the next sign-in.')
        return redirect('two_factor_manage')
    device = StaticDevice.objects.filter(user=request.user).first()
    current = _token_hash(request.COOKIES.get(TRUSTED_COOKIE, '')) if request.COOKIES.get(TRUSTED_COOKIE) else None
    return render(request, 'core/two_factor_manage.html', {
        'backup_left': device.token_set.count() if device else 0,
        'app_device': TOTPDevice.objects.filter(user=request.user, confirmed=True).first(),
        'trusted': TrustedDevice.objects.filter(user=request.user, expires_at__gt=timezone.now()),
        'current_hash': current,
        'trusted_days': TRUSTED_DAYS,
    })
