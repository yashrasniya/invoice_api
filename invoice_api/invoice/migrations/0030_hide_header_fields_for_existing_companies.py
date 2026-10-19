"""
Existing companies keep their invoice editor as it was: the six optional
header fields start hidden for them, and an admin can switch any back on in
UI Config -> Invoice Fields. Companies created after this migration have no
settings row, which means "everything shown" (see invoice.header_config).

Idempotent: a company that already has a settings row is left alone, so
re-running (or running after someone configured theirs) changes nothing.
The field keys are spelled out here rather than imported, so this migration
means the same thing even if the live list changes later.
"""
from django.db import migrations

KEYS = ('place_of_supply', 'payment_terms', 'payment_status',
        'payment_method', 'customer_notes', 'terms')


def hide_for_existing_companies(apps, schema_editor):
    Company = apps.get_model('accounts', 'UserCompanies')
    Config = apps.get_model('invoice', 'InvoiceHeaderConfig')

    already = set(Config.objects.values_list('company_id', flat=True))
    hidden = {key: {'visible': False, 'use_default': False, 'default': None} for key in KEYS}
    Config.objects.bulk_create([
        Config(company_id=company_id, fields=dict(hidden))
        for company_id in Company.objects.values_list('id', flat=True)
        if company_id not in already
    ])


class Migration(migrations.Migration):

    dependencies = [
        ('invoice', '0029_invoice_header_config'),
    ]

    operations = [
        # Not reversible in a meaningful way: afterwards there is no telling a
        # hidden-by-this-migration row from one an admin saved. The rows are
        # dropped with the table if 0029 is reversed.
        migrations.RunPython(hide_for_existing_companies, migrations.RunPython.noop),
    ]
