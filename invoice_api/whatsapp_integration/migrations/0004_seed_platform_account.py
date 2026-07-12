"""
Create the default platform WhatsApp account, seeded from the existing
environment variables if present. Product Owner can edit the details and
the default daily limit in Platform Admin.
"""
import os

from django.db import migrations


def forwards(apps, schema_editor):
    PlatformWhatsAppAccount = apps.get_model(
        'whatsapp_integration', 'PlatformWhatsAppAccount')
    if not PlatformWhatsAppAccount.objects.exists():
        PlatformWhatsAppAccount.objects.create(
            name='Default account',
            phone_number_id=os.getenv('PHONE_NUMBER_ID') or None,
            access_token=os.getenv('ACCESS_TOKEN') or None,
            business_account_id=os.getenv('WHATSAPP_BUSINESS_ACCOUNT_ID') or None,
            is_active=True,
            default_daily_limit=10,
        )


def backwards(apps, schema_editor):
    PlatformWhatsAppAccount = apps.get_model(
        'whatsapp_integration', 'PlatformWhatsAppAccount')
    PlatformWhatsAppAccount.objects.filter(name='Default account').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('whatsapp_integration', '0003_platformwhatsappaccount_companywhatsappsettings'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
