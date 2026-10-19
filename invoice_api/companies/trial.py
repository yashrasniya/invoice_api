"""15-day free trial: no card, full Pro, one per company.

A trial is an ordinary `CompanySubscription` row with status='trialing', so feature gating (middleware) and the
one-working-subscription constraint need no changes. `UserCompanies.trial_used_at` is the single eligibility
record. When the trial ends without payment the `expire_subscriptions` job drops the company to Free.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from companies.models import CompanySubscription, SubscriptionPlan

logger = logging.getLogger(__name__)

TRIAL_DAYS = 15
TRIAL_PLAN_CODE = 'pro'
FREE_PLAN_CODE = 'free'


def trial_days_left(subscription):
    """Whole days left in a trial, or None when `subscription` is not a trial. Today counts as a day left."""
    if subscription is None or subscription.status != 'trialing':
        return None
    return max(0, (subscription.end_date - timezone.localdate()).days)


@transaction.atomic
def start_trial(company):
    """Grant the trial. Returns the subscription, or None if ineligible/not configured. Idempotent."""
    from accounts.models import UserCompanies

    # lock the company row so two concurrent calls cannot both pass the eligibility check
    company = UserCompanies.objects.select_for_update().get(pk=company.pk)
    if company.trial_used_at:
        return None
    if CompanySubscription.objects.filter(
            company=company, status__in=['active', 'trialing']).exists():
        return None
    plan = SubscriptionPlan.objects.filter(code=TRIAL_PLAN_CODE, is_active=True).first()
    if plan is None:
        logger.warning("trial: no active '%s' plan; skipping trial for company=%s",
                       TRIAL_PLAN_CODE, company.pk)
        return None

    today = timezone.localdate()
    sub = CompanySubscription.objects.create(
        company=company, subscription_plan=plan, start_date=today,
        end_date=today + timedelta(days=TRIAL_DAYS), status='trialing',
        auto_renew=False)
    company.trial_used_at = timezone.now()
    company.save(update_fields=['trial_used_at'])
    return sub


def start_trial_or_free(company):
    """New-company bootstrap: trial if eligible, otherwise the default Free plan."""
    sub = start_trial(company)
    if sub is not None:
        return sub
    if CompanySubscription.objects.filter(
            company=company, status__in=['active', 'trialing']).exists():
        return None
    free = SubscriptionPlan.objects.filter(code=FREE_PLAN_CODE, is_active=True).first()
    if free is None:
        return None
    today = timezone.localdate()
    return CompanySubscription.objects.create(
        company=company, subscription_plan=free, start_date=today,
        end_date=today + timedelta(days=365), status='active', auto_renew=True)
