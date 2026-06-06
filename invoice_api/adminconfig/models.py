from django.db import models
from django.conf import settings
from rest_framework_simplejwt.tokens import AccessToken
import datetime

# Create your models here.
class Xl_download_config(models.Model):
    model = models.CharField(max_length=50)
    array = models.TextField(max_length=50000)

    def __str__(self):
        return self.model


class AdminJWTToken(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='admin_jwt_tokens')
    name = models.CharField(max_length=255, help_text="A friendly name or description for this token.")
    token = models.TextField(blank=True, null=True, help_text="The auto-generated JWT token.")
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True, help_text="Deactivate to immediately revoke access for this token.")

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        super().save(*args, **kwargs)
        if is_new and not self.token:
            access = AccessToken.for_user(self.user)
            access.set_exp(lifetime=datetime.timedelta(days=3650))
            access['token_id'] = self.id
            self.token = str(access)
            super().save(update_fields=['token'])

    def __str__(self):
        return f"{self.name} ({self.user.username})"