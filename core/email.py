"""
Email delivery helpers.

Railway blocks outgoing SMTP on its Free, Trial and Hobby plans, so production can send
through Brevo's HTTPS API instead (set BREVO_API_KEY). SMTP still works where it is allowed.
"""
import base64
import json
import logging
import urllib.error
import urllib.request
from email.utils import parseaddr

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)

BREVO_URL = 'https://api.brevo.com/v3/smtp/email'
BREVO_BACKEND = 'core.email.BrevoEmailBackend'
SMTP_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
NON_DELIVERING_BACKENDS = {
    'django.core.mail.backends.console.EmailBackend',
    'django.core.mail.backends.dummy.EmailBackend',
    'django.core.mail.backends.filebased.EmailBackend',
}


def email_problem():
    """Why email cannot be delivered with the current settings, or None when it is set up."""
    backend = settings.EMAIL_BACKEND
    if backend in NON_DELIVERING_BACKENDS:
        return 'email is not configured for delivery (the server only prints messages to its log)'
    if backend == BREVO_BACKEND and not settings.BREVO_API_KEY:
        return 'email is not configured: BREVO_API_KEY is missing'
    if backend == SMTP_BACKEND and not settings.EMAIL_HOST:
        return 'email is not configured: set BREVO_API_KEY (or EMAIL_HOST for SMTP)'
    return None


def _address(value):
    name, email = parseaddr(value)
    return {'email': email, 'name': name} if name else {'email': email}


class BrevoEmailBackend(BaseEmailBackend):
    """Sends mail through Brevo's transactional email API over HTTPS."""

    def send_messages(self, email_messages):
        sent = 0
        for message in email_messages:
            try:
                self._send(message)
                sent += 1
            except Exception:
                if not self.fail_silently:
                    raise
                logger.exception('Brevo email to %s failed', message.to)
        return sent

    def _send(self, message):
        payload = {
            'sender': _address(message.from_email or settings.DEFAULT_FROM_EMAIL),
            'to': [_address(addr) for addr in message.to],
            'subject': message.subject,
            'textContent': message.body,
        }
        if message.cc:
            payload['cc'] = [_address(addr) for addr in message.cc]
        if message.bcc:
            payload['bcc'] = [_address(addr) for addr in message.bcc]
        if message.reply_to:
            payload['replyTo'] = _address(message.reply_to[0])
        for alternative in getattr(message, 'alternatives', []) or []:
            content, mimetype = alternative[0], alternative[1]
            if mimetype == 'text/html':
                payload['htmlContent'] = content
        attachments = []
        for attachment in message.attachments:
            if isinstance(attachment, tuple) or hasattr(attachment, 'filename'):
                filename, content = attachment[0], attachment[1]
                if isinstance(content, str):
                    content = content.encode()
                attachments.append({'name': filename, 'content': base64.b64encode(content).decode()})
        if attachments:
            payload['attachment'] = attachments

        request = urllib.request.Request(
            BREVO_URL,
            data=json.dumps(payload).encode(),
            headers={
                'api-key': settings.BREVO_API_KEY,
                'accept': 'application/json',
                'content-type': 'application/json',
            },
            method='POST',
        )
        try:
            with urllib.request.urlopen(request, timeout=settings.EMAIL_TIMEOUT) as response:
                response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors='replace')[:500]
            raise RuntimeError(f'Brevo rejected the email (HTTP {exc.code}): {detail}') from exc
