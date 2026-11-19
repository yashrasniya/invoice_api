"""
Plan limit enforcement (PlanFeature.limits).

Usage:
    enforce_limit(request, 'invoicing', 'invoices_per_month', current_usage)
Raises LimitExceeded → handled as 403 `upgrade_required`.
"""
from django.core.cache import cache

from .permissions import UpgradeRequired


class LimitExceeded(UpgradeRequired):
    default_detail = 'Plan limit reached.'


FREE_PLAN_CODE = 'free'


def is_free_plan(request):
    """True when the company is on the Free plan (or has no working subscription).

    A trialing Pro subscription has a non-free plan_code, so trial users are not free.
    """
    sub = getattr(request, 'subscription', None)
    if sub is None:
        from .middleware import get_active_subscription
        company = getattr(getattr(request, 'user', None), 'user_company', None)
        sub = get_active_subscription(company) if company else {}
    plan_code = (sub or {}).get('plan_code')
    return not plan_code or plan_code == FREE_PLAN_CODE


def get_limit(request, feature_code, limit_key):
    """Read a numeric limit from the active plan; None = unlimited.

    A company with no active/working subscription (e.g. between a downgrade
    being scheduled and it actually taking effect) isn't plan-less — it's on
    the Free plan by default, so fall back to Free's limits rather than
    blocking the feature outright.
    """
    from companies.models import PlanFeature, SubscriptionPlan

    sub = getattr(request, 'subscription', None) or {}
    plan_id = sub.get('plan_id')
    if not plan_id:
        free_plan = SubscriptionPlan.objects.filter(code=FREE_PLAN_CODE).first()
        plan_id = free_plan.id if free_plan else None
    if not plan_id:
        return 0
    pf = (PlanFeature.objects
          .filter(subscription_plan_id=plan_id, feature__code=feature_code)
          .first())
    limits = (pf.limits if pf else {})
    return limits.get(limit_key)


def enforce_limit(request, feature_code, limit_key, current_usage):
    limit = get_limit(request, feature_code, limit_key)
    if limit is not None and current_usage >= limit:
        raise LimitExceeded(f"Plan limit reached: {limit_key} <= {limit}")
