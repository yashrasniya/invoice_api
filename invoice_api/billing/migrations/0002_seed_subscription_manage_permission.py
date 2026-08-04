"""Seed the `subscription.manage` permission and grant it to Company Admins.

`accounts/authz_seed.py` gains this code for newly created companies
automatically, but existing tenants already have their roles built, so they
need a backfill. Without it no tenant admin can reach the billing endpoints.
"""
from django.db import migrations

CODE = 'subscription.manage'
NAME = 'Manage subscription & billing'
ADMIN_ROLE = 'Company Admin'


def forwards(apps, schema_editor):
    CompanyPermission = apps.get_model('accounts', 'CompanyPermission')
    CompanyRole = apps.get_model('accounts', 'CompanyRole')

    perm, _ = CompanyPermission.objects.get_or_create(
        code=CODE, company=None,
        defaults={'name': NAME, 'is_system_permission': True,
                  'permission_type': 'CUSTOM'})

    # Anyone who can already manage the company gets billing too.
    for role in CompanyRole.objects.filter(name=ADMIN_ROLE):
        role.permissions.add(perm)


def backwards(apps, schema_editor):
    CompanyPermission = apps.get_model('accounts', 'CompanyPermission')
    CompanyPermission.objects.filter(code=CODE, company=None).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0001_initial'),
        # ('accounts', '0010_alter_companygroup_options_alter_companyrole_options_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
