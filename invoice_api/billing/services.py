"""Billing business logic.

Rules this module enforces, and why:

1. **Entitlement is granted by webhooks, never by the browser.** The Checkout
   callback is verified and used only to trigger an immediate re-sync so the UI
   updates without waiting for the webhook.
2. **Amounts always come from the database**, never from the request. A client
   picks a plan code and a period; the price is looked up server-side.
3. **Every entitlement write takes a row lock** on the company's
   CompanySubscription so concurrent webhooks cannot interleave.
4. **Upgrades apply immediately, downgrades at period end.** A downgrade never
   refunds and never shortens paid-for access.
"""
import logging
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.models import AuditLog
from companies.models import CompanySubscription, SubscriptionPlan

from .models import (BILLING_PERIOD_CHOICES, MONTHLY, TOTAL_COUNT, YEARLY,
                     BillingSubscription, PaymentRecord, RazorpayPlan,
                     ScheduledPlanChange, price_for, to_paise)
from .razorpay_client import BillingUnavailable, get_client, razorpay_call

logger = logging.getLogger('billing')

VALID_PERIODS = {p for p, _ in BILLING_PERIOD_CHOICES}
PERIOD_DAYS = {MONTHLY: 30, YEARLY: 365}
FREE_PLAN_CODE = 'free'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ts(unix_value):
    """Razorpay timestamps are Unix seconds. Return an aware datetime or None.

    Uses stdlib UTC rather than `django.utils.timezone.utc`, which is
    deprecated in Django 4.1 and removed in 5.0.
    """
    if not unix_value:
        return None
    return datetime.fromtimestamp(int(unix_value), tz=dt_timezone.utc)


def _localdate(dt=None):
    """Local (Asia/Kolkata) calendar date — never `timezone.now().date()`,
    which silently yields the UTC date and rolls over 5.5h early."""
    if dt is None:
        return timezone.localdate()
    return timezone.localtime(dt).date()


def validate_period(period: str) -> str:
    if period not in VALID_PERIODS:
        raise ValidationError({'period': f"Must be one of {sorted(VALID_PERIODS)}."})
    return period


def get_free_plan():
    return SubscriptionPlan.objects.filter(code=FREE_PLAN_CODE).first()


def is_free(plan: SubscriptionPlan, period: str) -> bool:
    return price_for(plan, period) <= 0


def audit(company, user, action, resource_id, data):
    try:
        AuditLog.objects.create(
            company=company, user=user, action=action,
            resource_type='BILLING', resource_id=str(resource_id), new_data=data)
    except Exception:  # auditing must never break a payment flow
        logger.exception("billing: failed to write audit log")


# ---------------------------------------------------------------------------
# Plan sync
# ---------------------------------------------------------------------------

def _adopt_existing_plan(plan: SubscriptionPlan, period: str, amount: int):
    """Look for a matching plan already on the Razorpay account and reuse it.

    Razorpay has no delete-plan API, so a failed run can leave orphans behind.
    Matching on (notes.plan_code, notes.period, amount, period) lets a retry
    adopt the orphan instead of creating yet another plan — which is how an
    account ends up rate-limited in the first place.
    """
    client = get_client()
    rzp_period = 'monthly' if period == MONTHLY else 'yearly'
    try:
        listing = razorpay_call(client.plan.all, {'count': 100})
    except BillingUnavailable:
        return None

    for item in listing.get('items', []):
        notes = item.get('notes') or {}
        item_detail = item.get('item') or {}
        if (notes.get('plan_code') == plan.code
                and notes.get('period') == period
                and item.get('period') == rzp_period
                and item_detail.get('amount') == amount):
            logger.info("billing: adopting existing razorpay plan %s for %s/%s",
                        item['id'], plan.code, period)
            return item
    return None


def ensure_razorpay_plan(plan: SubscriptionPlan, period: str,
                         allow_create: bool = True) -> RazorpayPlan:
    """Return a live Razorpay plan mapping for (plan, period).

    Resolution order: local mapping → adopt a matching plan already on the
    Razorpay account → create a new one.

    `allow_create=False` is used on the customer checkout path. Creating plans
    there is a mistake: Razorpay rate-limits plan creation, so a burst of
    signups (or one impatient customer clicking twice) trips the limit and
    leaves orphan plans behind. Plans are provisioned by
    `manage.py sync_razorpay_plans` at deploy time instead.
    """
    validate_period(period)
    amount = to_paise(price_for(plan, period))
    if amount <= 0:
        raise ValidationError(
            f"Plan '{plan.code}' is free for {period} billing; it has no Razorpay plan.")

    existing = RazorpayPlan.objects.filter(
        subscription_plan=plan, period=period, is_active=True).first()
    if existing and not existing.is_stale:
        return existing

    adopted = _adopt_existing_plan(plan, period, amount)
    if adopted is None:
        if not allow_create:
            raise BillingUnavailable(
                f"The '{plan.name}' {period} plan has not been set up in Razorpay "
                "yet. A Product Owner needs to run `manage.py sync_razorpay_plans` "
                "(or use Sync plans in Platform Admin) before anyone can subscribe.",
                status_code=503)

        client = get_client()
        payload = {
            'period': 'monthly' if period == MONTHLY else 'yearly',
            'interval': 1,
            'item': {
                'name': f"{plan.name} ({period})",
                'amount': amount,
                'currency': 'INR',
                'description': (plan.description or f"{plan.name} subscription")[:255],
            },
            'notes': {'plan_code': plan.code, 'period': period},
        }
        adopted = razorpay_call(client.plan.create, payload)
        logger.info("billing: created razorpay plan %s for %s/%s",
                    adopted['id'], plan.code, period)

    with transaction.atomic():
        if existing:
            existing.is_active = False
            existing.save(update_fields=['is_active', 'updated_at'])
        mapping, _ = RazorpayPlan.objects.get_or_create(
            razorpay_plan_id=adopted['id'],
            defaults={'subscription_plan': plan, 'period': period,
                      'amount_paise': amount})
        return mapping


def sync_all_plans():
    """Ensure a Razorpay plan exists for every priced plan/period. Returns a report."""
    report = []
    for plan in SubscriptionPlan.objects.filter(is_active=True).order_by('id'):
        for period in (MONTHLY, YEARLY):
            if is_free(plan, period):
                report.append((plan.code, period, 'skipped (free)'))
                continue
            try:
                rp = ensure_razorpay_plan(plan, period)
                report.append((plan.code, period, rp.razorpay_plan_id))
            except Exception as exc:
                report.append((plan.code, period, f"ERROR: {exc}"))
    return report


# ---------------------------------------------------------------------------
# Entitlement (drives CompanySubscription)
# ---------------------------------------------------------------------------

@transaction.atomic
def apply_entitlement(company, plan: SubscriptionPlan, *, status='active',
                      start_date=None, end_date=None, auto_renew=True):
    """Set the company's entitlement, holding a row lock throughout.

    There is a partial unique constraint allowing only one active/trialing
    CompanySubscription per company, so we mutate the existing row rather than
    inserting a second one.
    """
    today = _localdate()
    start_date = start_date or today
    if end_date is None:
        end_date = start_date + timedelta(days=PERIOD_DAYS[MONTHLY])

    rows = list(CompanySubscription.objects
                .select_for_update()
                .filter(company=company)
                .order_by('-start_date'))

    working = next((r for r in rows if r.status in ('active', 'trialing')), None)
    target = working or (rows[0] if rows else None)

    if target is None:
        sub = CompanySubscription.objects.create(
            company=company, subscription_plan=plan, start_date=start_date,
            end_date=end_date, status=status, auto_renew=auto_renew)
    else:
        target.subscription_plan = plan
        target.start_date = start_date
        target.end_date = end_date
        target.status = status
        target.auto_renew = auto_renew
        target.save(update_fields=['subscription_plan', 'start_date', 'end_date',
                                   'status', 'auto_renew', 'updated_at'])
        sub = target

    logger.info("billing: entitlement company=%s plan=%s status=%s until=%s",
                company.id, plan.code, status, end_date)
    return sub


def revert_to_free(company, reason=''):
    """Drop a company back to the Free plan (cancellation, completion, expiry)."""
    free = get_free_plan()
    if not free:
        logger.error("billing: no 'free' plan exists; cannot revert company=%s", company.id)
        return None
    today = _localdate()
    return apply_entitlement(
        company, free, status='active', start_date=today,
        end_date=today + timedelta(days=365), auto_renew=False)


# ---------------------------------------------------------------------------
# Subscription lifecycle
# ---------------------------------------------------------------------------

def get_live_subscription(company):
    return (BillingSubscription.objects
            .filter(company=company, status__in=BillingSubscription.LIVE_STATUSES)
            .select_related('subscription_plan')
            .order_by('-created_at')
            .first())


def _resolve_plan(plan_code: str) -> SubscriptionPlan:
    plan = SubscriptionPlan.objects.filter(code=plan_code, is_active=True).first()
    if not plan:
        raise ValidationError({'plan_code': f"Unknown or inactive plan '{plan_code}'."})
    return plan


def start_subscription(company, plan_code: str, period: str, user=None):
    """Create a Razorpay subscription for a company that has no live mandate.

    Returns the payload the frontend needs to open Checkout. No entitlement is
    granted here — that happens when `subscription.activated` arrives.
    """
    validate_period(period)
    plan = _resolve_plan(plan_code)

    if is_free(plan, period):
        raise ValidationError(
            {'plan_code': "The Free plan does not require payment. "
                          "Cancel your current subscription instead."})

    if get_live_subscription(company):
        raise ValidationError(
            {'detail': "This company already has an active subscription. "
                       "Use the change-plan endpoint to switch plans."})

    rp_plan = ensure_razorpay_plan(plan, period, allow_create=False)
    client = get_client()

    payload = {
        'plan_id': rp_plan.razorpay_plan_id,
        'total_count': TOTAL_COUNT[period],
        'quantity': 1,
        'customer_notify': 1,
        'notes': {
            'company_id': str(company.id),
            'company_name': (company.company_name or '')[:100],
            'plan_code': plan.code,
            'period': period,
        },
    }
    created = razorpay_call(client.subscription.create, payload)

    sub = BillingSubscription.objects.create(
        company=company, subscription_plan=plan, period=period,
        razorpay_subscription_id=created['id'],
        razorpay_plan_id=rp_plan.razorpay_plan_id,
        status=created.get('status', 'created'),
        short_url=created.get('short_url'),
        total_count=created.get('total_count') or TOTAL_COUNT[period],
        charge_at=_ts(created.get('charge_at')),
        created_by=user, notes=payload['notes'],
    )
    audit(company, user, 'CREATE', sub.razorpay_subscription_id,
          {'plan': plan.code, 'period': period, 'action': 'subscription_created'})
    return sub


def _direction(current_plan, new_plan, period):
    """+1 upgrade, -1 downgrade, 0 same price."""
    a = price_for(current_plan, period)
    b = price_for(new_plan, period)
    return (b > a) - (b < a)


def proration_preview(company, plan_code: str, period: str):
    """What a plan change would cost/credit today. Display only — Razorpay
    computes the authoritative amount when the change is applied."""
    validate_period(period)
    new_plan = _resolve_plan(plan_code)
    live = get_live_subscription(company)
    entitlement = (CompanySubscription.objects
                   .filter(company=company).order_by('-start_date').first())

    today = _localdate()
    days_left = 0
    unused_credit = Decimal('0')

    if entitlement and entitlement.end_date >= today:
        days_left = (entitlement.end_date - today).days
        if live:
            daily = price_for(live.subscription_plan, live.period) / Decimal(
                PERIOD_DAYS[live.period])
            unused_credit = (daily * days_left).quantize(Decimal('0.01'))

    new_price = price_for(new_plan, period)
    direction = _direction(live.subscription_plan, new_plan, period) if live else 1

    return {
        'plan_code': new_plan.code,
        'plan_name': new_plan.name,
        'period': period,
        'new_price': str(new_price),
        'days_remaining': days_left,
        'unused_credit': str(unused_credit),
        'direction': 'upgrade' if direction > 0 else ('downgrade' if direction < 0 else 'same'),
        'effective': 'immediately' if direction > 0 else (
            entitlement.end_date.isoformat() if entitlement and direction < 0 else 'immediately'),
        'requires_new_mandate': bool(live and live.period != period),
    }


@transaction.atomic
def change_plan(company, plan_code: str, period: str, user=None):
    """Upgrade now / downgrade at period end.

    Same billing period → Razorpay's own `update subscription` is used with
    `schedule_change_at`, which preserves the customer's existing mandate so no
    re-authorisation is needed.

    Different billing period → Razorpay cannot move a mandate between periods,
    so the old subscription is cancelled and a fresh one is created. The caller
    must send the customer back through Checkout; `requires_checkout` says so.
    """
    validate_period(period)
    new_plan = _resolve_plan(plan_code)
    live = get_live_subscription(company)

    # --- No live mandate: this is just a fresh subscribe ------------------
    if not live:
        if is_free(new_plan, period):
            revert_to_free(company)
            return {'requires_checkout': False, 'effect': 'switched_to_free'}
        sub = start_subscription(company, plan_code, period, user=user)
        return {'requires_checkout': True, 'effect': 'created',
                'subscription': sub}

    if live.subscription_plan_id == new_plan.id and live.period == period:
        raise ValidationError({'detail': "Already on this plan and billing period."})

    # --- Downgrade to Free: cancel at cycle end ---------------------------
    if is_free(new_plan, period):
        cancel_subscription(company, at_cycle_end=True, user=user)
        return {'requires_checkout': False, 'effect': 'downgrade_scheduled',
                'effective_date': _effective_date(company)}

    direction = _direction(live.subscription_plan, new_plan, period)
    upgrading = direction > 0 or (direction == 0 and period == YEARLY)

    # --- Period change: must re-authorise on a new mandate ----------------
    if live.period != period:
        rp_plan = ensure_razorpay_plan(new_plan, period, allow_create=False)
        client = get_client()
        if upgrading:
            razorpay_call(client.subscription.cancel,
                          live.razorpay_subscription_id, {'cancel_at_cycle_end': 0})
            live.status = 'cancelled'
        else:
            razorpay_call(client.subscription.cancel,
                          live.razorpay_subscription_id, {'cancel_at_cycle_end': 1})
            live.cancel_at_cycle_end = True
        live.save(update_fields=['status', 'cancel_at_cycle_end', 'updated_at'])

        new_sub = start_subscription(company, plan_code, period, user=user)
        new_sub.razorpay_plan_id = rp_plan.razorpay_plan_id
        new_sub.save(update_fields=['razorpay_plan_id'])
        audit(company, user, 'UPDATE', new_sub.razorpay_subscription_id,
              {'action': 'period_change', 'from': live.period, 'to': period})
        return {'requires_checkout': True, 'effect': 'period_change',
                'subscription': new_sub}

    # --- Same period: reuse the mandate -----------------------------------
    rp_plan = ensure_razorpay_plan(new_plan, period, allow_create=False)
    client = get_client()
    schedule_at = 'now' if upgrading else 'cycle_end'
    razorpay_call(client.subscription.edit, live.razorpay_subscription_id, {
        'plan_id': rp_plan.razorpay_plan_id,
        'schedule_change_at': schedule_at,
        'quantity': 1,
    })

    if upgrading:
        live.subscription_plan = new_plan
        live.razorpay_plan_id = rp_plan.razorpay_plan_id
        live.save(update_fields=['subscription_plan', 'razorpay_plan_id', 'updated_at'])
        # Grant the new plan immediately; the webhook will refresh the dates.
        entitlement = (CompanySubscription.objects
                       .filter(company=company).order_by('-start_date').first())
        apply_entitlement(
            company, new_plan, status='active',
            start_date=_localdate(),
            end_date=entitlement.end_date if entitlement else
            _localdate() + timedelta(days=PERIOD_DAYS[period]))
        audit(company, user, 'UPDATE', live.razorpay_subscription_id,
              {'action': 'upgrade', 'to': new_plan.code, 'period': period})
        return {'requires_checkout': False, 'effect': 'upgraded'}

    # Downgrade: queue it, keep serving the current plan until period end.
    effective = _effective_date(company)
    ScheduledPlanChange.objects.filter(company=company, status='pending').update(
        status='cancelled')
    ScheduledPlanChange.objects.create(
        company=company, from_plan=live.subscription_plan, to_plan=new_plan,
        period=period, effective_date=effective, billing_subscription=live,
        created_by=user)
    audit(company, user, 'UPDATE', live.razorpay_subscription_id,
          {'action': 'downgrade_scheduled', 'to': new_plan.code,
           'effective': effective.isoformat()})
    return {'requires_checkout': False, 'effect': 'downgrade_scheduled',
            'effective_date': effective}


def _effective_date(company):
    entitlement = (CompanySubscription.objects
                   .filter(company=company).order_by('-start_date').first())
    today = _localdate()
    if entitlement and entitlement.end_date > today:
        return entitlement.end_date
    return today


@transaction.atomic
def cancel_subscription(company, at_cycle_end=True, user=None):
    """Cancel the mandate. At cycle end by default so paid time is not lost."""
    live = get_live_subscription(company)
    if not live:
        raise ValidationError({'detail': "No active subscription to cancel."})

    client = get_client()
    razorpay_call(client.subscription.cancel, live.razorpay_subscription_id,
                  {'cancel_at_cycle_end': 1 if at_cycle_end else 0})

    live.cancel_at_cycle_end = bool(at_cycle_end)
    if not at_cycle_end:
        live.status = 'cancelled'
        live.ended_at = timezone.now()
        live.save(update_fields=['status', 'ended_at', 'cancel_at_cycle_end', 'updated_at'])
        revert_to_free(company, reason='cancelled immediately')
    else:
        live.save(update_fields=['cancel_at_cycle_end', 'updated_at'])
        free = get_free_plan()
        if free:
            ScheduledPlanChange.objects.filter(
                company=company, status='pending').update(status='cancelled')
            ScheduledPlanChange.objects.create(
                company=company, from_plan=live.subscription_plan, to_plan=free,
                period=live.period, effective_date=_effective_date(company),
                billing_subscription=live, created_by=user)

    audit(company, user, 'DELETE', live.razorpay_subscription_id,
          {'action': 'cancel', 'at_cycle_end': bool(at_cycle_end)})
    return live


def resume_after_cancel(company, user=None):
    """Undo a pending 'cancel at cycle end' while the mandate is still live."""
    live = get_live_subscription(company)
    if not live or not live.cancel_at_cycle_end:
        raise ValidationError({'detail': "Nothing scheduled to cancel."})
    # Razorpay cannot un-cancel; the customer must re-subscribe at period end.
    # What we can do is drop our queued downgrade so nothing changes locally.
    ScheduledPlanChange.objects.filter(
        company=company, status='pending').update(status='cancelled')
    audit(company, user, 'UPDATE', live.razorpay_subscription_id,
          {'action': 'cancel_reverted_locally'})
    return live


# ---------------------------------------------------------------------------
# Applying Razorpay state (used by webhooks and by manual re-sync)
# ---------------------------------------------------------------------------

@transaction.atomic
def apply_subscription_entity(entity: dict, company=None):
    """Reconcile a Razorpay subscription entity into our models + entitlement.

    Safe to call repeatedly with the same payload — this is what makes webhook
    replay harmless.
    """
    rzp_id = entity.get('id')
    if not rzp_id:
        return None

    sub = (BillingSubscription.objects
           .select_for_update()
           .filter(razorpay_subscription_id=rzp_id)
           .select_related('subscription_plan', 'company')
           .first())
    if sub is None:
        logger.warning("billing: subscription %s is unknown to us; ignoring", rzp_id)
        return None

    status = entity.get('status') or sub.status
    sub.status = status
    sub.razorpay_customer_id = entity.get('customer_id') or sub.razorpay_customer_id
    sub.current_start = _ts(entity.get('current_start')) or sub.current_start
    sub.current_end = _ts(entity.get('current_end')) or sub.current_end
    sub.charge_at = _ts(entity.get('charge_at'))
    sub.ended_at = _ts(entity.get('ended_at'))
    sub.paid_count = entity.get('paid_count') or sub.paid_count
    sub.total_count = entity.get('total_count') or sub.total_count
    sub.last_synced_at = timezone.now()

    # A plan change scheduled at cycle end lands here as a new plan_id.
    new_rzp_plan_id = entity.get('plan_id')
    if new_rzp_plan_id and new_rzp_plan_id != sub.razorpay_plan_id:
        mapping = RazorpayPlan.objects.filter(
            razorpay_plan_id=new_rzp_plan_id).select_related('subscription_plan').first()
        if mapping:
            sub.razorpay_plan_id = new_rzp_plan_id
            sub.subscription_plan = mapping.subscription_plan
            sub.period = mapping.period

    sub.save()

    company = company or sub.company
    _apply_status_to_entitlement(sub, company)
    return sub


def _apply_status_to_entitlement(sub: BillingSubscription, company):
    """Map a Razorpay subscription status onto CompanySubscription."""
    today = _localdate()
    end_date = _localdate(sub.current_end) if sub.current_end else None

    if sub.status == 'active':
        apply_entitlement(
            company, sub.subscription_plan, status='active',
            start_date=_localdate(sub.current_start) if sub.current_start else today,
            end_date=end_date or today + timedelta(days=PERIOD_DAYS[sub.period]),
            auto_renew=not sub.cancel_at_cycle_end)

    elif sub.status in ('pending', 'halted'):
        # A charge failed. Keep the plan but mark past_due so the existing
        # 7-day grace window in CompanySubscription.is_working() applies.
        apply_entitlement(
            company, sub.subscription_plan, status='past_due',
            start_date=_localdate(sub.current_start) if sub.current_start else today,
            end_date=end_date or today, auto_renew=False)

    elif sub.status in ('cancelled', 'completed', 'expired'):
        pending = ScheduledPlanChange.objects.filter(
            company=company, status='pending').first()
        if pending and pending.effective_date <= today:
            _apply_scheduled_change(pending)
        else:
            revert_to_free(company, reason=f"subscription {sub.status}")

    # 'created' and 'authenticated' grant nothing — the customer has approved a
    # mandate but has not been charged for a cycle yet.


def record_payment(payment: dict, subscription_entity: dict = None):
    """Idempotently record a payment. Keyed on Razorpay's payment id."""
    payment_id = payment.get('id')
    if not payment_id:
        return None

    sub = None
    if subscription_entity and subscription_entity.get('id'):
        sub = BillingSubscription.objects.filter(
            razorpay_subscription_id=subscription_entity['id']).first()

    company = sub.company if sub else None
    if company is None:
        notes = payment.get('notes') or {}
        company_id = notes.get('company_id')
        if company_id:
            from accounts.models import UserCompanies
            company = UserCompanies.objects.filter(pk=company_id).first()
    if company is None:
        logger.warning("billing: payment %s has no resolvable company", payment_id)
        return None

    defaults = {
        'company': company,
        'billing_subscription': sub,
        'subscription_plan': sub.subscription_plan if sub else None,
        'razorpay_invoice_id': payment.get('invoice_id'),
        'razorpay_order_id': payment.get('order_id'),
        'amount_paise': payment.get('amount') or 0,
        'currency': payment.get('currency') or 'INR',
        'status': payment.get('status') or 'captured',
        'method': payment.get('method'),
        'description': (payment.get('description') or '')[:255] or None,
        'error_description': payment.get('error_description'),
        'paid_at': _ts(payment.get('created_at')),
        'raw': payment,
    }
    record, created = PaymentRecord.objects.update_or_create(
        razorpay_payment_id=payment_id, defaults=defaults)
    if created:
        logger.info("billing: recorded payment %s (%s paise) for company=%s",
                    payment_id, defaults['amount_paise'], company.id)
    return record


# ---------------------------------------------------------------------------
# Scheduled downgrades
# ---------------------------------------------------------------------------

@transaction.atomic
def _apply_scheduled_change(change: ScheduledPlanChange):
    change = (ScheduledPlanChange.objects
              .select_for_update().filter(pk=change.pk, status='pending').first())
    if not change:
        return None  # already applied by a concurrent worker

    today = _localdate()
    if is_free(change.to_plan, change.period):
        revert_to_free(change.company, reason='scheduled downgrade')
    else:
        apply_entitlement(
            change.company, change.to_plan, status='active', start_date=today,
            end_date=today + timedelta(days=PERIOD_DAYS[change.period]))

    change.status = 'applied'
    change.applied_at = timezone.now()
    change.save(update_fields=['status', 'applied_at'])
    audit(change.company, change.created_by, 'UPDATE', change.pk,
          {'action': 'scheduled_change_applied', 'to': change.to_plan.code})
    return change


def apply_due_scheduled_changes():
    """Apply every downgrade whose effective date has arrived. Idempotent."""
    today = _localdate()
    due = ScheduledPlanChange.objects.filter(
        status='pending', effective_date__lte=today).select_related(
        'company', 'to_plan', 'from_plan')
    applied = []
    for change in due:
        try:
            if _apply_scheduled_change(change):
                applied.append(change)
        except Exception:
            logger.exception("billing: failed to apply scheduled change %s", change.pk)
    return applied


# ---------------------------------------------------------------------------
# Re-sync (used by the Checkout callback and the admin "reconcile" action)
# ---------------------------------------------------------------------------

def sync_subscription(billing_sub: BillingSubscription):
    """Pull the authoritative state from Razorpay and apply it."""
    client = get_client()
    entity = razorpay_call(client.subscription.fetch,
                           billing_sub.razorpay_subscription_id)
    return apply_subscription_entity(entity, company=billing_sub.company)
