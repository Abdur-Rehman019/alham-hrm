from django.contrib.auth import get_user_model
from django.contrib.auth.forms import PasswordResetForm
from django.core.mail import EmailMultiAlternatives
from django.db.models import Q
from django.template import loader


class EmployeePasswordResetForm(PasswordResetForm):
    """
    Finds the account by its login email or by the email on the employee's HR record,
    since many logins were created without an email of their own.
    """

    def get_users(self, email):
        users = get_user_model()._default_manager.filter(
            Q(email__iexact=email) | Q(employee_profile__email__iexact=email),
            is_active=True,
        ).distinct()
        for user in users:
            if not user.has_usable_password():
                continue
            if not user.email:
                # Send to the address that matched, and keep it on the login for next time.
                user.email = email
                type(user).objects.filter(pk=user.pk).update(email=email)
            yield user

    def send_mail(self, subject_template_name, email_template_name, context, from_email, to_email,
                  html_email_template_name=None):
        # Django's version logs and swallows delivery errors; let them reach the view so the user is told.
        subject = ''.join(loader.render_to_string(subject_template_name, context).splitlines())
        body = loader.render_to_string(email_template_name, context)
        message = EmailMultiAlternatives(subject, body, from_email, [to_email])
        if html_email_template_name:
            message.attach_alternative(loader.render_to_string(html_email_template_name, context), 'text/html')
        message.send()
