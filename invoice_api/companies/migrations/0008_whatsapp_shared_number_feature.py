"""
Seed the `whatsapp_shared_number` feature (send via the product's shared
WhatsApp account) and attach it to the default plans with per-day caps.
Product Owner can adjust per plan in Platform Admin.
"""
from django.core.cache import cache
from django.db import migrations

FEATURE = ('whatsapp_shared_number', 'Shared WhatsApp Number',
           "Send invoices via the product's WhatsApp number")

PLAN_LIMITS = {
    'free': {'sends_per_day': 5},
    'pro': {'sends_per_day': 50},
    'enterprise': {},  # falls back to the platform account's default limit
}


def forwards(apps, schema_editor):
    Feature = apps.get_model('companies', 'Feature')
    SubscriptionPlan = apps.get_model('companies', 'SubscriptionPlan')
    PlanFeature = apps.get_model('companies', 'PlanFeature')

    code, name, desc = FEATURE
    feature, _ = Feature.objects.get_or_create(
        code=code, defaults={'name': name, 'description': desc})

    for plan_code, limits in PLAN_LIMITS.items():
        plan = SubscriptionPlan.objects.filter(code=plan_code).first()
        if plan:
            PlanFeature.objects.get_or_create(
                subscription_plan=plan, feature=feature,
                defaults={'limits': limits})
    try:
        cache.clear()
    except Exception:
        pass


def backwards(apps, schema_editor):
    Feature = apps.get_model('companies', 'Feature')
    Feature.objects.filter(code=FEATURE[0]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('companies', '0007_migrate_legacy_subscriptions'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
