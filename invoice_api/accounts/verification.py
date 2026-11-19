"""Email ownership proof: a signed, expiring link mailed to the address on the account."""
import logging
import os
import threading
from email.mime.image import MIMEImage

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.core.mail import EmailMultiAlternatives
from django.utils.html import escape

logger = logging.getLogger(__name__)

SALT = 'accounts.verify-email'
MAX_AGE_SECONDS = 3 * 24 * 3600
APP_NAME = 'Orvine Invoice'
BRAND_COLOR = '#4f46e5'  # matches the mobile/web primary
# Logo is attached inline (cid:), so it renders without any public hosting.
LOGO_PATH = os.path.join(settings.BASE_DIR, 'static', 'email', 'orvine_logo_email.png')
LOGO_CID = 'orvine-logo'


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


def _render(user, link):
    """(subject, plain text, HTML) for the verification mail. Table layout and inline styles for mail clients."""
    name = user.first_name or 'there'
    subject = f'Confirm your email for {APP_NAME}'
    text = (
        f"Hi {name},\n\n"
        f"Welcome to {APP_NAME}! Please confirm your email address to finish setting up your account:\n\n"
        f"{link}\n\n"
        "This link works for 3 days. If you didn't create an account, you can safely ignore this email.\n\n"
        f"— The {APP_NAME} team"
    )
    html = f"""<!doctype html>
<html>
<body style="margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;color:#0f172a;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f1f5f9;padding:32px 16px;">
  <tr><td align="center">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:520px;background:#ffffff;border-radius:12px;overflow:hidden;">
      <tr><td style="padding:24px 32px;border-bottom:1px solid #e2e8f0;">
        <table role="presentation" cellspacing="0" cellpadding="0"><tr>
          <td style="padding-right:12px;vertical-align:middle;"><img src="cid:{LOGO_CID}" width="40" height="41" alt="{escape(APP_NAME)} logo" style="display:block;border:0;width:40px;height:41px;"></td>
          <td style="vertical-align:middle;font-size:18px;font-weight:700;color:#0f172a;">{escape(APP_NAME)}</td>
        </tr></table>
      </td></tr>
      <tr><td style="padding:32px;">
        <h1 style="margin:0 0 16px;font-size:22px;line-height:1.3;">Confirm your email address</h1>
        <p style="margin:0 0 16px;font-size:15px;line-height:1.6;color:#334155;">Hi {escape(name)},</p>
        <p style="margin:0 0 24px;font-size:15px;line-height:1.6;color:#334155;">
          Welcome to {escape(APP_NAME)}! Tap the button below to verify your email and finish setting up your account.
        </p>
        <table role="presentation" cellspacing="0" cellpadding="0" style="margin:0 0 24px;">
          <tr><td style="border-radius:8px;background:{BRAND_COLOR};">
            <a href="{escape(link)}" style="display:inline-block;padding:14px 28px;font-size:15px;font-weight:600;color:#ffffff;text-decoration:none;border-radius:8px;">Verify email address</a>
          </td></tr>
        </table>
        <p style="margin:0 0 8px;font-size:13px;line-height:1.6;color:#64748b;">Button not working? Copy and paste this link into your browser:</p>
        <p style="margin:0 0 24px;font-size:13px;line-height:1.6;word-break:break-all;"><a href="{escape(link)}" style="color:{BRAND_COLOR};">{escape(link)}</a></p>
        <hr style="border:none;border-top:1px solid #e2e8f0;margin:0 0 16px;">
        <p style="margin:0;font-size:12px;line-height:1.6;color:#94a3b8;">This link works for 3 days. If you didn't create an account, you can safely ignore this email.</p>
      </td></tr>
    </table>
    <p style="margin:16px 0 0;font-size:12px;color:#94a3b8;">{escape(APP_NAME)}</p>
  </td></tr>
</table>
</body>
</html>"""
    return subject, text, html


def _send(user, link):
    try:
        subject, text, html = _render(user, link)
        message = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [user.email])
        message.attach_alternative(html, 'text/html')
        if os.path.exists(LOGO_PATH):
            # 'related' keeps the inline image attached to the HTML part, so the cid: reference resolves
            message.mixed_subtype = 'related'
            with open(LOGO_PATH, 'rb') as f:
                logo = MIMEImage(f.read(), 'png')
            logo.add_header('Content-ID', f'<{LOGO_CID}>')
            logo.add_header('Content-Disposition', 'inline', filename='orvine_logo.png')
            message.attach(logo)
        message.send(fail_silently=False)
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
