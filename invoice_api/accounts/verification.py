"""Email ownership proof: a signed, expiring link mailed to the address on the account."""
import logging
import threading

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.core.mail import send_mail

logger = logging.getLogger(__name__)

SALT = 'accounts.verify-email'
MAX_AGE_SECONDS = 3 * 24 * 3600


def make_token(user):
    # the address is signed in too, so changing the email on the account kills links mailed to the old one
    return signing.dumps({'uid': user.pk, 'email': user.email.lower()}, salt=SALT)


def read_token(token):
    """(user_id, email) for a valid link, else None."""
    try:
        data = signing.loads(token, salt=SALT, max_age=MAX_AGE_SECONDS)
    except signing.BadSignature:
        return None
    return data['uid'], data['email']


def _send(user, link):
    try:
        send_mail(
            'Verify your email',
            f"Hi {user.first_name or 'there'},\n\nConfirm your email address to finish setting up your account:\n"
            f"{link}\n\nThe link works for 3 days. If you didn't create an account, you can ignore this email.",
            settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
    except Exception:
        logger.exception("Could not send the verification email to user %s", user.pk)


def send_verification_email(request, user, background=True):
    """Mail the link. Never raises: a mail outage must not break signup (the app offers a resend)."""
    if not user.email or user.email_verified:
        return
    link = request.build_absolute_uri(f'/api/verify-email/{make_token(user)}/')
    if background:
        threading.Thread(target=_send, args=(user, link), daemon=True).start()
    else:
        _send(user, link)


def may_resend(user):
    """One resend a minute per account (cache.add is atomic: only the first caller in the window wins)."""
    return cache.add(f'verify-email-resend:{user.pk}', 1, timeout=60)
