"""Account deletion: a person asks, we lock the account and tell an admin; an admin (Django admin action) or the
`purge_deleted_accounts` command removes everything later. Invoices, customers and vendors belong to the user who
created them, so the permanent step is a real delete of that user and what cascades from them."""
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from accounts.signals import audit_muted

logger = logging.getLogger(__name__)

PURGE_AFTER_DAYS = 40


def request_deletion(user):
    """Lock the account now (sign-in and existing tokens stop working) and notify the admin."""
    with transaction.atomic():
        user.deletion_requested_at = timezone.now()
        user.is_active = False
        user.save(update_fields=['deletion_requested_at', 'is_active'])
        # stop pushing this person's notifications to their phones straight away
        user.device_tokens.all().delete()
    _notify_admin(user)


def _notify_admin(user):
    recipients = [e.strip() for e in getattr(settings, 'ACCOUNT_DELETION_NOTIFY_EMAILS', []) if e.strip()]
    if not recipients:
        logger.warning("account deletion requested by %s but ACCOUNT_DELETION_NOTIFY_EMAILS is empty", user.username)
        return
    company = user.user_company
    due = user.deletion_requested_at + timedelta(days=PURGE_AFTER_DAYS)
    body = (
        f"{user.username} ({user.email or 'no email'}) has asked to delete their account.\n\n"
        f"Name: {user.name() or '-'}\n"
        f"Company: {company.company_name if company else '-'}"
        f"{' (company admin)' if user.is_company_admin else ''}\n"
        f"Requested: {user.deletion_requested_at:%Y-%m-%d %H:%M}\n\n"
        f"Their account is locked now. To remove everything immediately: Django admin > Users > select them > "
        f"action \"Permanently delete accounts that asked to be deleted\". Otherwise it is removed automatically "
        f"on {due:%Y-%m-%d} (when `manage.py purge_deleted_accounts` runs).\n\n"
        f"Check the company's subscription first: deleting does not cancel an active paid plan."
    )
    try:
        send_mail(f"Account deletion request: {user.username}", body, settings.DEFAULT_FROM_EMAIL, recipients,
                  fail_silently=False)
    except Exception:  # the request must still succeed; the admin can find it in the admin list
        logger.exception("could not email the account deletion notice for %s", user.username)


def due_for_purge(now=None):
    from accounts.models import User
    cutoff = (now or timezone.now()) - timedelta(days=PURGE_AFTER_DAYS)
    return User.objects.filter(deletion_requested_at__isnull=False, deletion_requested_at__lte=cutoff)


def purge_user(user):
    """Permanently delete a user who asked to be deleted, and their company if nobody else is left in it.
    Returns a short description for logs/admin messages. Refuses anyone who has not asked, and superusers."""
    if user.deletion_requested_at is None or user.is_superuser:
        raise ValueError(f"{user.username} has not asked to be deleted")
    username, company = user.username, user.user_company
    with transaction.atomic(), audit_muted():
        for f in (user.profile,):
            if f:
                f.delete(save=False)
        user.delete()
        company_removed = False
        if company is not None and not company.user_set.exists():
            if company.company_logo:
                company.company_logo.delete(save=False)
            company.delete()
            company_removed = True
    logger.info("purged account %s%s", username, " and its company" if company_removed else "")
    return f"{username}{' + company' if company_removed else ''}"


def purge_user_and_company(user):
    """Admin-only hard delete that does NOT require the user to have asked: removes the user, their whole company
    (every member, invoice, customer, vendor, ...). Refuses superusers, and companies that contain a superuser."""
    if user.is_superuser:
        raise ValueError(f"{user.username} is a superuser")
    company = user.user_company
    if company is not None and company.user_set.filter(is_superuser=True).exists():
        raise ValueError(f"{user.username}'s company contains a superuser")
    username = user.username
    with transaction.atomic(), audit_muted():
        if user.profile:
            user.profile.delete(save=False)
        if company is None:
            user.delete()
            label = username
        else:
            name = company.company_name
            members = list(company.user_set.all())
            for m in members:
                if m.profile:
                    m.profile.delete(save=False)
            if company.company_logo:
                company.company_logo.delete(save=False)
            company.delete()  # cascades to members and everything the company owns
            label = f"{username} + company '{name}' ({len(members)} user(s))"
    logger.warning("FULL purge by admin: %s", label)
    return label
