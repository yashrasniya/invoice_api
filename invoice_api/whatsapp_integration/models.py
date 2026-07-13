from django.db import models
from django.conf import settings
from invoice_api.softdelete import SoftDeleteModel

class WhatsAppIntegration(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('active', 'Active'),
        ('failed', 'Failed'),
    )

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='whatsapp_integration')
    business_account_id = models.CharField(max_length=255, blank=True, null=True)
    phone_number_id = models.CharField(max_length=255, blank=True, null=True)
    access_token = models.TextField(blank=True, null=True)
    webhook_verify_token = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    default_template_name = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"{self.user.username} - {self.status}"


class WhatsAppTemplate(SoftDeleteModel):
    CATEGORY_CHOICES = (
        ('utility', 'Utility'),
        ('marketing', 'Marketing'),
        ('authentication', 'Authentication'),
    )
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='whatsapp_templates')
    template_name = models.CharField(max_length=255)
    template_body = models.TextField()
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='utility')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    meta_template_id = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.template_name} ({self.status}) - {self.user.username}"


class PlatformWhatsAppAccount(models.Model):
    """The product's shared WhatsApp account, managed by the Product Owner.
    Companies without their own number can send through this account
    (requires the whatsapp_shared_number plan feature)."""
    name = models.CharField(max_length=255, default='Default account')
    business_account_id = models.CharField(max_length=255, blank=True, null=True)
    phone_number_id = models.CharField(max_length=255, blank=True, null=True)
    access_token = models.TextField(blank=True, null=True)
    default_template_name = models.CharField(max_length=255, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    # default per-company daily send cap; a plan's whatsapp_shared_number
    # limits {"sends_per_day": N} overrides this
    default_daily_limit = models.PositiveIntegerField(default=10)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({'active' if self.is_active else 'inactive'})"

    @classmethod
    def get_active(cls):
        return cls.objects.filter(is_active=True).order_by('id').first()


class CompanyWhatsAppSettings(models.Model):
    """Per-company choice of WhatsApp sending mode."""
    MODE_CHOICES = (
        ('platform', 'Use the product WhatsApp number'),
        ('own', 'Use own WhatsApp number'),
    )
    company = models.OneToOneField(
        'accounts.UserCompanies', on_delete=models.CASCADE,
        related_name='whatsapp_settings')
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default='platform')
    # invoice PDF template used when sharing on WhatsApp without an
    # explicit choice — saves picking a template on every send
    default_invoice_template = models.ForeignKey(
        'yaml_manager.Yaml', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+')
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.company} → {self.mode}"


class WhatsAppMessage(models.Model):
    STATUS_CHOICES = (
        ('queued', 'Queued'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='whatsapp_messages')
    phone_number_id = models.CharField(max_length=255)
    recipient_number = models.CharField(max_length=50)
    message_body = models.TextField(blank=True, null=True)
    template_id = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='queued')
    meta_message_id = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"To {self.recipient_number} ({self.status})"
