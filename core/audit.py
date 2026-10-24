"""
Audit trail. A middleware remembers who is making the current request; model signals then record
every create / change / delete of the tracked models with old and new values.
Bulk queryset.update() calls skip signals, so views that use them call record() themselves.
"""
import contextvars
import datetime
import decimal

from django.contrib.auth import get_user_model
from django.db.models.fields.files import FieldFile
from django.db.models.signals import post_delete, post_save, pre_save

_current = contextvars.ContextVar('audit_request', default=None)

# model label -> (category, fields to track). Passwords are tracked as "changed", never by value.
TRACKED = {
    'employees.Employee': ('employee', [
        'name', 'cnic', 'date_of_birth', 'role', 'monthly_salary', 'phone', 'email', 'address',
        'joined_on', 'leaving_date', 'is_active', 'photo', 'user',
    ]),
    'payroll.Payroll': ('payroll', ['base_salary', 'leave_deduction', 'incentive_total', 'net_pay', 'is_approved']),
    'payroll.IncentiveRule': ('incentive', ['destination_country', 'amount']),
    'payroll.StudentEnrollment': ('incentive', [
        'student_name', 'destination_country', 'counselor', 'confirmed_on', 'incentive_amount', 'incentive_paid',
    ]),
    'auth.User': ('account', ['username', 'email', 'is_active', 'is_staff', 'is_superuser', 'password']),
}
SECRET_FIELDS = {'password'}


class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _current.set(request)
        try:
            return self.get_response(request)
        finally:
            _current.reset(token)


def _actor():
    from .middleware import client_ip
    request = _current.get()
    if request is None:
        return None, 'system', ''
    user = getattr(request, 'user', None)
    if user is not None and user.is_authenticated:
        return user, user.get_username(), client_ip(request)
    return None, 'anonymous', client_ip(request)


def _plain(value):
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, (datetime.date, datetime.time)):
        return value.isoformat()
    if isinstance(value, FieldFile):
        return value.name or None
    return str(value)


def _snapshot(instance, fields):
    values = {}
    for field in fields:
        model_field = instance._meta.get_field(field)
        attname = model_field.attname  # foreign keys: compare ids, not objects
        values[field] = _plain(getattr(instance, attname))
    return values


def _describe(instance):
    if instance._meta.label == 'auth.User':
        return f"login {instance.get_username()}"
    return str(instance)[:200]


def record(instance, action, changes=None, note=''):
    """Write one audit entry; also used directly by views for things signals cannot see."""
    from .models import AuditLog
    label = instance._meta.label
    category = TRACKED.get(label, ('employee', []))[0]
    actor, actor_name, ip = _actor()
    AuditLog.objects.create(
        actor=actor, actor_name=actor_name, ip_address=ip or '',
        category=category, action=action,
        object_type=instance._meta.verbose_name.title(),
        object_id=str(instance.pk or ''), object_repr=_describe(instance),
        changes=changes or {}, note=note[:255],
    )


def _before_save(sender, instance, **kwargs):
    fields = TRACKED[sender._meta.label][1]
    old = sender._default_manager.filter(pk=instance.pk).first() if instance.pk else None
    instance._audit_before = _snapshot(old, fields) if old is not None else None


def _after_save(sender, instance, created, raw=False, update_fields=None, **kwargs):
    if raw:  # loading fixtures
        return
    fields = TRACKED[sender._meta.label][1]
    before = getattr(instance, '_audit_before', None)
    after = _snapshot(instance, fields)
    if created or before is None:
        changes = {f: [None, '(set)' if f in SECRET_FIELDS else v] for f, v in after.items() if v not in (None, '', False)}
        record(instance, 'create', changes)
        return
    changes = {}
    for field in fields:
        if before[field] != after[field]:
            changes[field] = ['(hidden)', '(changed)'] if field in SECRET_FIELDS else [before[field], after[field]]
    if not changes:  # e.g. a sign-in only updates last_login, which is not tracked
        return
    action = 'approve' if sender._meta.label == 'payroll.Payroll' and changes.get('is_approved') == [False, True] else 'update'
    record(instance, action, changes)


def _after_delete(sender, instance, **kwargs):
    fields = TRACKED[sender._meta.label][1]
    snapshot = _snapshot(instance, fields)
    record(instance, 'delete', {f: ['(hidden)' if f in SECRET_FIELDS else v, None]
                                for f, v in snapshot.items() if v not in (None, '', False)})


def _authenticator_removed(sender, instance, **kwargs):
    if instance.confirmed:
        record(instance.user, 'security', note='Authenticator app removed; two-factor must be set up again')


def connect():
    from django.apps import apps
    from django_otp.plugins.otp_totp.models import TOTPDevice
    post_delete.connect(_authenticator_removed, sender=TOTPDevice, dispatch_uid='audit-totp-del')
    for label in TRACKED:
        model = get_user_model() if label == 'auth.User' else apps.get_model(label)
        uid = f'audit-{label}'
        pre_save.connect(_before_save, sender=model, dispatch_uid=f'{uid}-pre')
        post_save.connect(_after_save, sender=model, dispatch_uid=f'{uid}-post')
        post_delete.connect(_after_delete, sender=model, dispatch_uid=f'{uid}-del')
