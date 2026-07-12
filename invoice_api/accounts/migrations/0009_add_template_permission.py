"""
Add the `template.manage` system permission and grant it to every existing
Company Admin system role. Members do NOT get it by default — tenant admins
decide who can access the template gallery/designer (via role, group or
direct grant in Access Control).
"""
from django.core.cache import cache
from django.db import migrations

CODE = 'template.manage'
NAME = 'Manage invoice templates'


def forwards(apps, schema_editor):
    CompanyPermission = apps.get_model('accounts', 'CompanyPermission')
    CompanyRole = apps.get_model('accounts', 'CompanyRole')

    perm, _ = CompanyPermission.objects.get_or_create(
        code=CODE, company=None,
        defaults={'name': NAME, 'is_system_permission': True,
                  'permission_type': 'CUSTOM'})

    for role in CompanyRole.objects.filter(is_system_role=True, name='Company Admin'):
        role.permissions.add(perm)

    try:
        cache.clear()  # historical models don't fire our signals
    except Exception:
        pass


def backwards(apps, schema_editor):
    CompanyPermission = apps.get_model('accounts', 'CompanyPermission')
    CompanyPermission.objects.filter(code=CODE, company=None).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_userinvite_and_more'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
