from django.db import models
from django.conf import settings

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


class WhatsAppTemplate(models.Model):
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
