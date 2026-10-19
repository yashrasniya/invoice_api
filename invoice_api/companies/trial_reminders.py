"""Day-12 ("3 days left") and day-15 ("last day") trial reminders: email + push to the company's admins.

Run daily (after `expire_subscriptions`):  python manage.py send_trial_reminders

Each reminder is stamped on the company, so reruns and catch-up runs never double-send. A company that has
already authorised a Razorpay mandate is skipped — it is converting, and "upgrade now" would only confuse it.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from accounts.models import User
from accounts.push import send_push
from companies.models import CompanySubscription

logger = logging.getLogger(__name__)

REMINDER_DAYS = 3  # "day 12" of a 15-day trial


def _copy(kind, days_left, company):
    name = company.company_name or 'your company'
    if kind == 'final':
        return ('Your free trial ends today',
                f"{name}'s Pro trial ends today. Upgrade now to keep creating invoices and using Pro features; "
                f"after today the account moves to the Free plan (your data stays safe and viewable).")
    return (f'{days_left} day{"s" if days_left != 1 else ""} left in your free trial',
            f"{name}'s Pro trial ends in {days_left} day{'s' if days_left != 1 else ''}. "
            f"Upgrade any time and you keep every remaining trial day — your first charge only happens when the trial ends.")


def _notify(company, kind, days_left):
    title, body = _copy(kind, days_left, company)
    link = f"{settings.FRONTEND_URL.rstrip('/')}/billing"
    admins = list(User.objects.filter(user_company=company, is_company_admin=True, is_active=True))
    for user in admins:
        if user.email:
            try:
                send_mail(title, f"Hi {user.first_name or 'there'},\n\n{body}\n\nUpgrade: {link}\n",
                          settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
            except Exception:
                logger.exception("trial reminder email failed for user %s", user.pk)
        send_push(user, title, body, {'type': 'trial_reminder', 'kind': kind})
    return len(admins)


def send_trial_reminders(today=None):
    """Returns {'3d': n, 'final': n} — companies reminded."""
    from billing.services import get_live_subscription

    today = today or timezone.localdate()
    sent = {'3d': 0, 'final': 0}
    trials = (CompanySubscription.objects
              .filter(status='trialing', end_date__gte=today,
                      end_date__lte=today + timedelta(days=REMINDER_DAYS))
              .select_related('company'))
    for sub in trials:
        company, days_left = sub.company, (sub.end_date - today).days
        if get_live_subscription(company):
            continue
        kind, field = (('final', 'trial_reminder_final_at') if days_left == 0
                       else ('3d', 'trial_reminder_3d_at'))
        if getattr(company, field) is not None:
            continue
        # stamp first: a crash mid-send then risks a missed reminder rather than a duplicate
        setattr(company, field, timezone.now())
        company.save(update_fields=[field])
        _notify(company, kind, days_left)
        sent[kind] += 1
    return sent
