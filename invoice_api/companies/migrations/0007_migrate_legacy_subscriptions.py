"""
Legacy subscription data migration:
1. Seed the Feature catalog and default plans (Free / Pro / Enterprise).
2. Map each legacy accounts.Subscriptions name to a SubscriptionPlan.
3. Create a CompanySubscription for every company:
   - companies with a legacy `subscriptions_plan` FK → the mapped plan
   - companies without one → the Free plan
   (The legacy FK stays nullable during the transition; removed in a
   follow-up release.)
"""
from datetime import timedelta

from django.db import migrations
from django.utils import timezone
from django.utils.text import slugify

FEATURES = [
    ('invoicing', 'Invoicing', "Create and manage invoices"),
    ('inventory', 'Inventory', "Inventory management"),
    ('whatsapp_integration', 'WhatsApp Integration', "Send invoices & alerts via WhatsApp"),
    ('advanced_reports', 'Advanced Reports', "Advanced reporting & export"),
    ('template_designer', 'Template Designer', "Custom invoice template designer"),
    ('api_access', 'API Access', "Service-token API access"),
]

PLANS = {
    'free': {
        'name': 'Free', 'monthly_price': 0, 'yearly_price': 0,
        'features': {
            'invoicing': {'invoices_per_month': 50, 'users': 2},
            'inventory': {},
        },
    },
    'pro': {
        'name': 'Pro', 'monthly_price': 499, 'yearly_price': 4999,
        'features': {
            'invoicing': {'invoices_per_month': 1000, 'users': 10},
            'inventory': {},
            'whatsapp_integration': {},
            'template_designer': {},
            'advanced_reports': {},
        },
    },
    'enterprise': {
        'name': 'Enterprise', 'monthly_price': 1999, 'yearly_price': 19999,
        'features': {
            'invoicing': {},
            'inventory': {},
            'whatsapp_integration': {},
            'template_designer': {},
            'advanced_reports': {},
            'api_access': {},
        },
    },
}


def forwards(apps, schema_editor):
    Feature = apps.get_model('companies', 'Feature')
    SubscriptionPlan = apps.get_model('companies', 'SubscriptionPlan')
    PlanFeature = apps.get_model('companies', 'PlanFeature')
    CompanySubscription = apps.get_model('companies', 'CompanySubscription')
    UserCompanies = apps.get_model('accounts', 'UserCompanies')

    features = {}
    for code, name, desc in FEATURES:
        features[code], _ = Feature.objects.get_or_create(
            code=code, defaults={'name': name, 'description': desc})

    plans = {}
    for code, spec in PLANS.items():
        plan, _ = SubscriptionPlan.objects.get_or_create(
            code=code,
            defaults={'name': spec['name'],
                      'monthly_price': spec['monthly_price'],
                      'yearly_price': spec['yearly_price']})
        plans[code] = plan
        for fcode, limits in spec['features'].items():
            PlanFeature.objects.get_or_create(
                subscription_plan=plan, feature=features[fcode],
                defaults={'limits': limits})

    today = timezone.now().date()
    one_year = today + timedelta(days=365)

    for company in UserCompanies.objects.select_related('subscriptions_plan'):
        if CompanySubscription.objects.filter(
                company=company, status__in=['active', 'trialing']).exists():
            continue

        legacy = company.subscriptions_plan
        if legacy and legacy.name:
            code = slugify(legacy.name).replace('-', '_') or 'free'
            plan = plans.get(code)
            if plan is None:
                plan, _ = SubscriptionPlan.objects.get_or_create(
                    code=code, defaults={'name': legacy.name,
                                         'monthly_price': 0, 'yearly_price': 0})
                # unknown legacy plans get the Free feature set
                for fcode, limits in PLANS['free']['features'].items():
                    PlanFeature.objects.get_or_create(
                        subscription_plan=plan, feature=features[fcode],
                        defaults={'limits': limits})
        else:
            plan = plans['free']

        CompanySubscription.objects.create(
            company=company, subscription_plan=plan,
            start_date=today, end_date=one_year,
            status='active', auto_renew=True)


def backwards(apps, schema_editor):
    CompanySubscription = apps.get_model('companies', 'CompanySubscription')
    CompanySubscription.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('companies', '0006_feature_subscriptionplan_planfeature_and_more'),
        ('accounts', '0007_seed_authz'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
