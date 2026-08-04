"""
Razorpay billing models.

Design notes
------------
* `CompanySubscription` (companies app) remains the single source of truth for
  *entitlement* — what a tenant is allowed to use. Nothing in this app is read
  by the feature gates directly.
* The models here record the *money* side: which Razorpay plan/subscription a
  company is on, what was charged, and which webhook events we have already
  processed.
* Webhooks drive entitlement. Client-side checkout callbacks are treated as a
  hint only (they trigger a re-sync), never as proof of payment.
"""
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.utils import timezone

from accounts.models import User, UserCompanies
from companies.models import SubscriptionPlan

MONTHLY = 'monthly'
YEARLY = 'yearly'

BILLING_PERIOD_CHOICES = [
    (MONTHLY, 'Monthly'),
    (YEARLY, 'Yearly'),
]

# Razorpay's `total_count` is the number of BILLING CYCLES a mandate covers —
# not years — and it is capped per period. Exceeding the cap is rejected with
# nothing more descriptive than "Validation failed", and the SDK discards the
# `field` that would tell you which parameter was at fault, so getting this
# wrong is very expensive to debug. It was previously 120 for monthly (read as
# "10 years"), which silently broke every monthly checkout.
MAX_TOTAL_COUNT = {MONTHLY: 100, YEARLY: 10}

# Sit at the ceiling: the longest mandate Razorpay will accept, after which the
# customer re-subscribes. 100 monthly cycles is ~8.3 years.
TOTAL_COUNT = {MONTHLY: 100, YEARLY: 10}

# Fail at startup rather than at a customer's checkout.
for _period, _count in TOTAL_COUNT.items():
    _cap = MAX_TOTAL_COUNT[_period]
    if _count > _cap:
        raise ImproperlyConfigured(
            f"TOTAL_COUNT[{_period!r}] is {_count}, above Razorpay's maximum of "
            f"{_cap} for a {_period} plan. Razorpay would reject every "
            f"subscription create with an opaque 'Validation failed'."
        )


def price_for(plan: SubscriptionPlan, period: str):
    """Rupee price of a plan for a billing period, as a Decimal."""
    return plan.yearly_price if period == YEARLY else plan.monthly_price


def to_paise(rupees) -> int:
    """Razorpay works in the smallest currency unit. Never use float here."""
    from decimal import Decimal, ROUND_HALF_UP
    return int((Decimal(rupees) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


class RazorpayPlan(models.Model):
    """Maps one of our SubscriptionPlans + a billing period to a Razorpay plan.

    Razorpay plans are immutable once created, so a price change requires a new
    Razorpay plan. `amount_paise` snapshots what was pushed; when it no longer
    matches the local plan price the row is stale and must be re-synced.
    """
    subscription_plan = models.ForeignKey(
        SubscriptionPlan, on_delete=models.CASCADE, related_name='razorpay_plans')
    period = models.CharField(max_length=10, choices=BILLING_PERIOD_CHOICES)
    razorpay_plan_id = models.CharField(max_length=64, unique=True, db_index=True)
    amount_paise = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default='INR')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['subscription_plan', 'period'],
                condition=models.Q(is_active=True),
                name='one_active_razorpay_plan_per_plan_period',
            )
        ]
        indexes = [models.Index(fields=['subscription_plan', 'period', 'is_active'])]

    def __str__(self):
        return f"{self.subscription_plan.code}/{self.period} → {self.razorpay_plan_id}"

    @property
    def is_stale(self) -> bool:
        return self.amount_paise != to_paise(
            price_for(self.subscription_plan, self.period))


class BillingSubscription(models.Model):
    """A Razorpay subscription (mandate) belonging to one company."""

    # Mirrors Razorpay's subscription lifecycle exactly — do not invent states.
    STATUS_CHOICES = [
        ('created', 'Created'),            # awaiting authorisation payment
        ('authenticated', 'Authenticated'),  # mandate approved, not yet started
        ('active', 'Active'),
        ('pending', 'Pending'),            # a charge failed, retrying
        ('halted', 'Halted'),              # all retries exhausted
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed'),        # ran out of billing cycles
        ('expired', 'Expired'),            # never authorised in time
    ]
    # States in which this subscription is the company's current mandate.
    LIVE_STATUSES = ('created', 'authenticated', 'active', 'pending', 'halted')
    # States in which the customer is actually paying us.
    PAYING_STATUSES = ('active', 'pending', 'halted')

    company = models.ForeignKey(
        UserCompanies, on_delete=models.CASCADE, related_name='billing_subscriptions')
    subscription_plan = models.ForeignKey(
        SubscriptionPlan, on_delete=models.PROTECT, related_name='billing_subscriptions')
    period = models.CharField(max_length=10, choices=BILLING_PERIOD_CHOICES)

    razorpay_subscription_id = models.CharField(max_length=64, unique=True, db_index=True)
    razorpay_plan_id = models.CharField(max_length=64)
    razorpay_customer_id = models.CharField(max_length=64, blank=True, null=True)

    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='created', db_index=True)
    short_url = models.URLField(blank=True, null=True)

    current_start = models.DateTimeField(null=True, blank=True)
    current_end = models.DateTimeField(null=True, blank=True)
    charge_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    total_count = models.PositiveIntegerField(default=0)
    paid_count = models.PositiveIntegerField(default=0)
    cancel_at_cycle_end = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='billing_subscriptions_created')
    notes = models.JSONField(default=dict, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['company', 'status']),
            models.Index(fields=['company', '-created_at']),
        ]

    def __str__(self):
        return f"{self.company_id} · {self.subscription_plan.code} · {self.status}"

    @property
    def is_live(self) -> bool:
        return self.status in self.LIVE_STATUSES


class ScheduledPlanChange(models.Model):
    """A downgrade queued to take effect at the end of the current period.

    Upgrades apply immediately and never create a row here.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('applied', 'Applied'),
        ('cancelled', 'Cancelled'),
    ]

    company = models.ForeignKey(
        UserCompanies, on_delete=models.CASCADE, related_name='scheduled_plan_changes')
    from_plan = models.ForeignKey(
        SubscriptionPlan, on_delete=models.PROTECT, related_name='+')
    to_plan = models.ForeignKey(
        SubscriptionPlan, on_delete=models.PROTECT, related_name='+')
    period = models.CharField(max_length=10, choices=BILLING_PERIOD_CHOICES)
    effective_date = models.DateField(db_index=True)

    billing_subscription = models.ForeignKey(
        BillingSubscription, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='scheduled_changes')
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['company'], condition=models.Q(status='pending'),
                name='one_pending_plan_change_per_company',
            )
        ]

    def __str__(self):
        return (f"{self.company_id}: {self.from_plan.code} → {self.to_plan.code} "
                f"on {self.effective_date} ({self.status})")


class PaymentRecord(models.Model):
    """One captured/failed Razorpay payment. Written only by the webhook."""
    STATUS_CHOICES = [
        ('created', 'Created'),
        ('authorized', 'Authorized'),
        ('captured', 'Captured'),
        ('refunded', 'Refunded'),
        ('failed', 'Failed'),
    ]

    company = models.ForeignKey(
        UserCompanies, on_delete=models.CASCADE, related_name='payment_records')
    billing_subscription = models.ForeignKey(
        BillingSubscription, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='payments')
    subscription_plan = models.ForeignKey(
        SubscriptionPlan, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+')

    razorpay_payment_id = models.CharField(max_length=64, unique=True, db_index=True)
    razorpay_invoice_id = models.CharField(max_length=64, blank=True, null=True)
    razorpay_order_id = models.CharField(max_length=64, blank=True, null=True)

    amount_paise = models.PositiveIntegerField()
    currency = models.CharField(max_length=3, default='INR')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, db_index=True)
    method = models.CharField(max_length=30, blank=True, null=True)
    description = models.CharField(max_length=255, blank=True, null=True)
    error_description = models.TextField(blank=True, null=True)

    paid_at = models.DateTimeField(null=True, blank=True)
    raw = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-paid_at', '-created_at']
        indexes = [models.Index(fields=['company', '-created_at'])]

    def __str__(self):
        return f"{self.razorpay_payment_id} · {self.amount_rupees} · {self.status}"

    @property
    def amount_rupees(self):
        from decimal import Decimal
        return Decimal(self.amount_paise) / 100


class WebhookEvent(models.Model):
    """Idempotency ledger for Razorpay webhooks.

    `event_id` comes from the `X-Razorpay-Event-Id` header. Razorpay retries
    aggressively and will replay the same event; processing must happen at most
    once, so this row is created before any state change and is the lock.
    """
    STATUS_CHOICES = [
        ('received', 'Received'),
        ('processed', 'Processed'),
        ('ignored', 'Ignored'),      # event type we do not act on
        ('failed', 'Failed'),
    ]

    event_id = models.CharField(max_length=128, unique=True, db_index=True)
    event = models.CharField(max_length=100, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='received', db_index=True)
    error = models.TextField(blank=True, null=True)
    company = models.ForeignKey(
        UserCompanies, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+')
    received_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-received_at']
        indexes = [models.Index(fields=['event', '-received_at'])]

    def __str__(self):
        return f"{self.event} · {self.event_id} · {self.status}"

    def mark(self, status, error=None):
        self.status = status
        self.error = error
        self.processed_at = timezone.now()
        self.save(update_fields=['status', 'error', 'processed_at'])
