"""
Seed the `eway_bill` feature (e-way bill details, bulk-upload JSON)
and attach it to the paid plans.
"""
from django.core.cache import cache
from django.db import migrations, transaction

FEATURE = ('eway_bill', 'E-way Bills',
           'Transport details and e-way bill JSON for invoices')

PLAN_LIMITS = {
    'pro': {},
    'enterprise': {},
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
        with transaction.atomic():  # savepoint: a missing cache table must not abort the migration on PostgreSQL
            cache.clear()
    except Exception:
        pass


def backwards(apps, schema_editor):
    Feature = apps.get_model('companies', 'Feature')
    Feature.objects.filter(code=FEATURE[0]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('companies', '0011_gst_phase2'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
