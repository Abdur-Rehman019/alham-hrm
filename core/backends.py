from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailOrUsernameBackend(ModelBackend):
    """
    Sign in with a username or an email address (the login's own email or the company email on
    the employee record), ignoring capitals. If one email belongs to several logins, nobody is
    signed in, so the person must use their username.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get(get_user_model().USERNAME_FIELD)
        if not username or password is None:
            return None
        username = username.strip()
        User = get_user_model()
        if '@' in username:
            users = list(User._default_manager.filter(
                Q(email__iexact=username) | Q(employee_profile__email__iexact=username)).distinct()[:2])
        else:
            users = list(User._default_manager.filter(username__iexact=username)[:2])
        if len(users) != 1:
            # Run the hasher anyway so a wrong name takes as long as a wrong password.
            User().set_password(password)
            return None
        user = users[0]
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
