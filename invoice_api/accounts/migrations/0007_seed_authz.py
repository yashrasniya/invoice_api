"""
Seed the authz system:
1. System permission catalog (company=NULL, is_system_permission=True).
2. Global `Product Owner` role; per-company `Company Admin` / `Member`
   system roles with default permission sets.
3. Bootstrap: every user with is_company_admin=True gets the Company Admin
   role for their company; superusers get Product Owner.
"""
from django.db import migrations

from accounts.authz_seed import (COMPANY_ADMIN_ROLE, MEMBER_CODES, MEMBER_ROLE,
                                 PRODUCT_OWNER_ROLE, SYSTEM_PERMISSIONS,
                                 TENANT_ADMIN_CODES)


def seed_authz(apps, schema_editor):
    CompanyPermission = apps.get_model('accounts', 'CompanyPermission')
    CompanyRole = apps.get_model('accounts', 'CompanyRole')
    UserCompanies = apps.get_model('accounts', 'UserCompanies')
    User = apps.get_model('accounts', 'User')

    # 1. permission catalog
    perms = {}
    for code, name in SYSTEM_PERMISSIONS:
        perm, _ = CompanyPermission.objects.get_or_create(
            code=code, company=None,
            defaults={'name': name, 'is_system_permission': True,
                      'permission_type': 'CUSTOM'})
        perms[code] = perm

    # 2. global Product Owner role
    po_role, _ = CompanyRole.objects.get_or_create(
        company=None, name=PRODUCT_OWNER_ROLE,
        defaults={'is_system_role': True,
                  'description': 'Platform staff: manage plans, features and all tenants.'})

    for su in User.objects.filter(is_superuser=True):
        po_role.users.add(su)

    # per-company system roles + admin bootstrap
    for company in UserCompanies.objects.all():
        admin_role, created = CompanyRole.objects.get_or_create(
            company=company, name=COMPANY_ADMIN_ROLE,
            defaults={'is_system_role': True,
                      'description': 'Full administrative access for this company.'})
        if created:
            admin_role.permissions.set([perms[c] for c in TENANT_ADMIN_CODES])

        member_role, created = CompanyRole.objects.get_or_create(
            company=company, name=MEMBER_ROLE,
            defaults={'is_system_role': True,
                      'description': 'Standard member access.'})
        if created:
            member_role.permissions.set([perms[c] for c in MEMBER_CODES])

        # 3. bootstrap from legacy boolean
        for user in User.objects.filter(user_company=company):
            if user.is_company_admin:
                admin_role.users.add(user)
            else:
                member_role.users.add(user)


def unseed_authz(apps, schema_editor):
    CompanyPermission = apps.get_model('accounts', 'CompanyPermission')
    CompanyRole = apps.get_model('accounts', 'CompanyRole')
    CompanyRole.objects.filter(
        is_system_role=True,
        name__in=[COMPANY_ADMIN_ROLE, MEMBER_ROLE, PRODUCT_OWNER_ROLE]).delete()
    CompanyPermission.objects.filter(
        company=None, is_system_permission=True,
        code__in=[c for c, _ in SYSTEM_PERMISSIONS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0006_companypermission_companyrole_companygroup_auditlog_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_authz, unseed_authz),
    ]
