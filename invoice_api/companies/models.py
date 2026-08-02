from datetime import timedelta

from django.db import models
from django.utils import timezone

from accounts.models import User
from invoice_api.softdelete import SoftDeleteModel


# ---------------------------------------------------------------------------
# Subscription system
# ---------------------------------------------------------------------------

class SubscriptionPlan(models.Model):
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=100, unique=True, db_index=True)
    description = models.TextField(blank=True)
    monthly_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    yearly_price = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Feature(models.Model):
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=100, unique=True, db_index=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class PlanFeature(models.Model):
    subscription_plan = models.ForeignKey(
        SubscriptionPlan, on_delete=models.CASCADE, related_name='plan_features')
    feature = models.ForeignKey(
        Feature, on_delete=models.CASCADE, related_name='plan_features')
    limits = models.JSONField(
        default=dict, blank=True,
        help_text="e.g. {'users': 5, 'invoices_per_month': 100}")

    class Meta:
        unique_together = ('subscription_plan', 'feature')

    def __str__(self):
        return f"{self.subscription_plan.code} / {self.feature.code}"


class CompanySubscription(models.Model):
    STATUS_CHOICES = [
        ('active', 'Active'),
        ('trialing', 'Trialing'),
        ('past_due', 'Past Due'),
        ('canceled', 'Canceled'),
        ('expired', 'Expired'),  # explicit terminal state set by expiry job
    ]
    GRACE_PERIOD_DAYS = 7  # past_due grace window

    company = models.ForeignKey(
        'accounts.UserCompanies', on_delete=models.CASCADE,
        related_name='company_subscriptions')
    # PROTECT: deleting a plan must not cascade-delete tenant subscriptions
    subscription_plan = models.ForeignKey(
        SubscriptionPlan, on_delete=models.PROTECT,
        related_name='company_subscriptions')
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='active', db_index=True)
    auto_renew = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # at most one working subscription per company
            models.UniqueConstraint(
                fields=['company'],
                condition=models.Q(status__in=['active', 'trialing']),
                name='one_active_subscription_per_company',
            )
        ]
        indexes = [models.Index(fields=['company', 'status', 'end_date'])]

    def __str__(self):
        return f"{self.company} → {self.subscription_plan} ({self.status})"

    def is_working(self):
        # localdate(), not now().date(): with USE_TZ and TIME_ZONE='Asia/Kolkata'
        # the latter yields the UTC date, so between 00:00 and 05:30 IST a
        # subscription starting today reads as not-yet-started and a customer
        # who just paid is locked out of the plan they bought.
        today = timezone.localdate()
        if self.status in ('active', 'trialing'):
            return self.start_date <= today <= self.end_date
        if self.status == 'past_due':  # grace period
            return today <= self.end_date + timedelta(days=self.GRACE_PERIOD_DAYS)
        return False


class Customers(SoftDeleteModel):
    # Basic Info
    name = models.CharField(max_length=255, default="Unnamed Company")
    legal_name = models.CharField(max_length=255, blank=True, default="", help_text="As per GST/PAN records")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    # Contact
    email = models.EmailField(max_length=255, blank=True, null=True, default=None)
    phone_number = models.CharField(max_length=15, blank=True, null=True, default=None)
    website = models.URLField(blank=True, null=True, default=None)

    # Address
    address = models.CharField(max_length=3000, blank=True, default="")
    city = models.CharField(max_length=100, blank=True, default="")
    district = models.CharField(max_length=100, blank=True, default="")
    state = models.CharField(max_length=100, blank=True, default="")
    state_code = models.IntegerField(blank=True, null=True, default=None, help_text="GST State Code")
    pincode = models.CharField(max_length=10, blank=True, default="")

    # Govt Identifiers
    gst_number = models.CharField(max_length=15, blank=True, default="", help_text="GSTIN (15 characters)")
    pan_number = models.CharField(max_length=10, blank=True, default="")

    # Banking Details
    bank_name = models.CharField(max_length=100, blank=True, default="")
    account_number = models.CharField(max_length=30, blank=True, default="")
    ifsc_code = models.CharField(max_length=11, blank=True, default="")
    branch = models.CharField(max_length=100, blank=True, default="")

    # Misc
    incorporation_date = models.DateField(blank=True, null=True, default=None)
    business_type = models.CharField(
        max_length=50,
        choices=[
            ("private_limited", "Private Limited"),
            ("public_limited", "Public Limited"),
            ("partnership", "Partnership"),
            ("sole_prop", "Sole Proprietorship"),
            ("llp", "LLP"),
            ("ngo", "NGO"),
            ("other", "Other"),
        ],
        default="sole_prop",
    )
    logo = models.ImageField(upload_to="company_logos/", blank=True, null=True, default=None)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name or "Unnamed Company"


class Vendor(SoftDeleteModel):
    # Basic Info
    name = models.CharField(max_length=255, default="Unnamed Vendor")
    legal_name = models.CharField(max_length=255, blank=True, default="", help_text="As per GST/PAN records")
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    # Contact
    email = models.EmailField(max_length=255, blank=True, null=True, default=None)
    phone_number = models.CharField(max_length=15, blank=True, null=True, default=None)
    website = models.URLField(blank=True, null=True, default=None)

    # Address
    address = models.CharField(max_length=3000, blank=True, default="")
    city = models.CharField(max_length=100, blank=True, default="")
    district = models.CharField(max_length=100, blank=True, default="")
    state = models.CharField(max_length=100, blank=True, default="")
    state_code = models.IntegerField(blank=True, null=True, default=None, help_text="GST State Code")
    pincode = models.CharField(max_length=10, blank=True, default="")

    # Govt Identifiers
    gst_number = models.CharField(max_length=15, blank=True, default="", help_text="GSTIN (15 characters)")
    pan_number = models.CharField(max_length=10, blank=True, default="")

    # Banking Details
    bank_name = models.CharField(max_length=100, blank=True, default="")
    account_number = models.CharField(max_length=30, blank=True, default="")
    ifsc_code = models.CharField(max_length=11, blank=True, default="")
    branch = models.CharField(max_length=100, blank=True, default="")

    # Misc
    business_type = models.CharField(
        max_length=50,
        choices=[
            ("private_limited", "Private Limited"),
            ("public_limited", "Public Limited"),
            ("partnership", "Partnership"),
            ("sole_prop", "Sole Proprietorship"),
            ("llp", "LLP"),
            ("ngo", "NGO"),
            ("other", "Other"),
        ],
        default="sole_prop",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name or "Unnamed Vendor"
