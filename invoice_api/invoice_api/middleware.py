"""
Tenant middleware & resolution helpers.

Key design points:
- CustomAuthentication (SimpleJWT via cookie) runs at the DRF view layer,
  AFTER Django middleware. So `request.company` / `request.features` /
  `request.permissions` are LAZY (SimpleLazyObject over TenantContext) and
  only resolve on first access — inside DRF permission classes, after auth.
- Membership is validated: a user may only act inside a company they belong
  to (Product Owner / platform staff exempt). Mismatch → 403, never fallback.
- ContextVars are reset with the token API in try/finally (no leaks).
- Caches fail open to the DB: a cache error degrades to slower, never wrong.
"""
import logging
from contextvars import ContextVar

from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from django.utils.functional import SimpleLazyObject

logger = logging.getLogger(__name__)

active_company_ctx = ContextVar('active_company_ctx', default=None)
current_user_ctx = ContextVar('current_user_ctx', default=None)  # AuditLog actor

PERM_CACHE_TTL = 300
SUB_CACHE_TTL = 3600
MISS_CACHE_TTL = 60  # short TTL for negative results


def get_current_company():
    return active_company_ctx.get()


def get_current_user():
    return current_user_ctx.get()


# ---------------------------------------------------------------------------
# Cached resolution helpers
# ---------------------------------------------------------------------------

def _cache_get(key):
    try:
        return cache.get(key)
    except Exception:  # cache down → query DB
        logger.warning("cache.get failed for %s", key, exc_info=True)
        return None


def _cache_set(key, value, timeout):
    try:
        cache.set(key, value, timeout=timeout)
    except Exception:
        logger.warning("cache.set failed for %s", key, exc_info=True)


def _perm_version(company_id):
    key = f"perm_ver:{company_id}"
    v = _cache_get(key)
    if v is None:
        v = 1
        _cache_set(key, v, timeout=None)
    return v


def bump_perm_version(company_id):
    """One INCR invalidates every user's cached permissions for the company."""
    try:
        cache.incr(f"perm_ver:{company_id}")
    except ValueError:
        _cache_set(f"perm_ver:{company_id}", 2, timeout=None)
    except Exception:
        logger.warning("perm version bump failed for company %s", company_id, exc_info=True)


def get_active_subscription(company):
    key = f"company_sub:{company.id}"
    data = _cache_get(key)
    if data is not None:
        return data

    from companies.models import CompanySubscription
    # localdate(): a UTC date excludes subscriptions that start today IST.
    today = timezone.localdate()
    sub = (CompanySubscription.objects
           .filter(company=company,
                   status__in=['active', 'trialing', 'past_due'],
                   start_date__lte=today)
           .select_related('subscription_plan')
           .order_by('-start_date')
           .first())

    if sub and sub.is_working():
        data = {'id': sub.id, 'plan_id': sub.subscription_plan_id,
                'plan_code': sub.subscription_plan.code, 'status': sub.status,
                'end_date': sub.end_date.isoformat()}
        # TTL must not outlive end_date
        seconds_left = max(60, int((sub.end_date - today).days * 86400))
        _cache_set(key, data, timeout=min(SUB_CACHE_TTL, seconds_left))
    else:
        data = {}
        _cache_set(key, data, timeout=MISS_CACHE_TTL)
    return data


def get_enabled_features(subscription):
    if not subscription or not subscription.get('plan_id'):
        return set()
    plan_id = subscription['plan_id']
    key = f"plan_features:{plan_id}"
    features = _cache_get(key)
    if features is None:
        from companies.models import PlanFeature
        features = set(PlanFeature.objects
                       .filter(subscription_plan_id=plan_id)
                       .values_list('feature__code', flat=True))
        _cache_set(key, features, timeout=SUB_CACHE_TTL)
    return features


def get_user_permissions(user, company, use_cache=True):
    if not company:
        return set()
    version = _perm_version(company.id)
    key = f"user_perms:{user.id}:{company.id}:v{version}"
    perms = _cache_get(key) if use_cache else None
    if perms is not None:
        return perms

    from django.db.models import Q
    from accounts.models import CompanyPermission, UserDirectPermission

    granted = set(CompanyPermission.objects.filter(
        Q(roles__users=user, roles__company=company,
          roles__is_deleted=False) |
        Q(roles__users=user, roles__company__isnull=True,
          roles__is_deleted=False) |  # global system roles
        Q(company_groups__users=user, company_groups__company=company,
          company_groups__is_deleted=False) |
        Q(roles__company_groups__users=user,
          roles__company_groups__company=company,
          roles__is_deleted=False,
          roles__company_groups__is_deleted=False)
    ).distinct().values_list('code', flat=True))

    # direct grants add, direct denies always win
    direct = (UserDirectPermission.objects
              .filter(user=user, company=company)
              .values_list('permission__code', 'is_granted'))
    for code, is_granted in direct:
        (granted.add if is_granted else granted.discard)(code)

    _cache_set(key, granted, timeout=PERM_CACHE_TTL)
    return granted


# ---------------------------------------------------------------------------
# Lazy tenant context
# ---------------------------------------------------------------------------

class TenantContext:
    """Lazily resolves tenant data on first access — i.e. AFTER DRF's
    CustomAuthentication has run, inside permission classes."""

    def __init__(self, request):
        self.request = request
        self._resolved = False
        self._company = None
        self._subscription = None
        self._features = None
        self._permissions = None

    def _resolve(self):
        if self._resolved:
            return
        self._resolved = True
        request = self.request
        user = request.user  # by now DRF has authenticated (JWT cookie/header)

        company = self._resolve_company(request, user)
        self._company = company
        active_company_ctx.set(company)  # context now available for TenantManager
        current_user_ctx.set(user if getattr(user, 'is_authenticated', False) else None)

        if company:
            self._subscription = get_active_subscription(company)
            self._features = get_enabled_features(self._subscription)
            self._permissions = (get_user_permissions(user, company)
                                 if getattr(user, 'is_authenticated', False) else set())
        else:
            self._subscription, self._features, self._permissions = None, set(), set()

    def _resolve_company(self, request, user):
        from accounts.models import UserCompanies
        candidate = None

        # A. Domain/subdomain mapping (optional, cache-fed)
        host = request.get_host().split(':')[0]
        company_id = _cache_get(f"domain_company:{host}")
        if company_id:
            candidate = UserCompanies.objects.filter(id=company_id).first()

        # B. JWT claim
        if candidate is None and isinstance(getattr(request, 'auth', None), dict):
            cid = request.auth.get('company_id')
            if cid:
                candidate = UserCompanies.objects.filter(id=cid).first()

        # C. X-Company-ID header
        if candidate is None:
            header = request.headers.get('X-Company-ID')
            if header and header.isdigit():
                candidate = UserCompanies.objects.filter(id=int(header)).first()

        # D. Fallback: user's own company
        if candidate is None and getattr(user, 'is_authenticated', False):
            candidate = getattr(user, 'user_company', None)

        # MEMBERSHIP VALIDATION — the resolved company must be one the user
        # belongs to, unless they are platform staff (Product Owner).
        if candidate is not None and getattr(user, 'is_authenticated', False):
            is_platform_staff = user.is_superuser or user.is_staff
            if not is_platform_staff and user.user_company_id != candidate.id:
                raise PermissionDenied("You do not belong to the requested company.")
        return candidate

    @property
    def company(self):
        self._resolve()
        return self._company

    @property
    def subscription(self):
        self._resolve()
        return self._subscription

    @property
    def features(self):
        self._resolve()
        return self._features

    @property
    def permissions(self):
        self._resolve()
        return self._permissions


def tenant_middleware(get_response):
    def middleware(request):
        ctx = TenantContext(request)
        request.tenant_ctx = ctx
        request.company = SimpleLazyObject(lambda: ctx.company)
        request.subscription = SimpleLazyObject(lambda: ctx.subscription)
        request.features = SimpleLazyObject(lambda: ctx.features)
        request.permissions = SimpleLazyObject(lambda: ctx.permissions)

        company_token = active_company_ctx.set(None)  # token-based reset
        user_token = current_user_ctx.set(None)
        try:
            return get_response(request)
        finally:
            active_company_ctx.reset(company_token)
            current_user_ctx.reset(user_token)
    return middleware
