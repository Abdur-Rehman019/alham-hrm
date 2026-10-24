"""
Two-factor sign-in for admin and staff accounts: an authenticator app code (TOTP) on every sign-in,
with one-time backup codes for a lost phone.
"""
import base64

import qrcode
import qrcode.image.svg
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods
from django_otp import login as otp_login
from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
from django_otp.plugins.otp_totp.models import TOTPDevice

from . import audit
from .middleware import is_admin_user

BACKUP_CODE_COUNT = 10


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
            return render(request, 'core/two_factor_backup_codes.html', {'codes': codes, 'first_time': True})
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
            return redirect(_next_url(request))
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
    device = StaticDevice.objects.filter(user=request.user).first()
    return render(request, 'core/two_factor_manage.html', {
        'backup_left': device.token_set.count() if device else 0,
        'app_device': TOTPDevice.objects.filter(user=request.user, confirmed=True).first(),
    })
