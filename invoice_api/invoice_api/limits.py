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


def get_limit(request, feature_code, limit_key):
    """Read a numeric limit from the active plan; None = unlimited, 0 = no plan."""
    sub = getattr(request, 'subscription', None) or {}
    plan_id = sub.get('plan_id')
    if not plan_id:
        return 0
    key = f"plan_limits:{plan_id}:{feature_code}"
    try:
        limits = cache.get(key)
    except Exception:
        limits = None
    if limits is None:
        from companies.models import PlanFeature
        pf = (PlanFeature.objects
              .filter(subscription_plan_id=plan_id, feature__code=feature_code)
              .first())
        limits = (pf.limits if pf else {})
        try:
            cache.set(key, limits, timeout=3600)
        except Exception:
            pass
    return limits.get(limit_key)


def enforce_limit(request, feature_code, limit_key, current_usage):
    limit = get_limit(request, feature_code, limit_key)
    if limit is not None and current_usage >= limit:
        raise LimitExceeded(f"Plan limit reached: {limit_key} <= {limit}")
