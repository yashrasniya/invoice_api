"""
Canonical authz seed data: system permission catalog & default roles.
Used by the seed migration AND by runtime bootstrap for newly created
companies (see accounts/signals.py).
"""

# (code, name) — system-wide permission catalog
SYSTEM_PERMISSIONS = [
    ('role.manage', 'Manage roles'),
    ('permission.assign', 'Assign permissions to users'),
    ('group.manage', 'Manage groups'),
    ('user.invite', 'Invite users'),
    ('user.manage', 'Manage users'),
    ('invoice.create', 'Create invoices'),
    ('invoice.view', 'View invoices'),
    ('invoice.update', 'Update invoices'),
    ('invoice.delete', 'Delete invoices'),
    ('customer.manage', 'Manage customers'),
    ('vendor.manage', 'Manage vendors'),
    ('inventory.manage', 'Manage inventory'),
    ('report.view', 'View reports'),
    ('report.export', 'Export reports'),
    ('whatsapp.send', 'Send WhatsApp messages'),
    ('whatsapp.manage', 'Manage WhatsApp integration'),
    ('template.manage', 'Manage invoice templates'),
    ('subscription.view', 'View subscription'),
    ('audit.view', 'View audit log'),
]

# Company Admin: every tenant-manageable permission
TENANT_ADMIN_CODES = [code for code, _ in SYSTEM_PERMISSIONS]

# Member: basic operational set
MEMBER_CODES = [
    'invoice.create', 'invoice.view', 'invoice.update',
    'customer.manage', 'vendor.manage', 'inventory.manage',
    'report.view', 'subscription.view',
]

COMPANY_ADMIN_ROLE = 'Company Admin'
MEMBER_ROLE = 'Member'
PRODUCT_OWNER_ROLE = 'Product Owner'


def ensure_system_permissions(CompanyPermission):
    """Idempotent: returns {code: permission} for the global catalog."""
    perms = {}
    for code, name in SYSTEM_PERMISSIONS:
        perm, _ = CompanyPermission.objects.get_or_create(
            code=code, company=None,
            defaults={'name': name, 'is_system_permission': True,
                      'permission_type': 'CUSTOM'})
        perms[code] = perm
    return perms


def ensure_company_roles(CompanyRole, CompanyPermission, company):
    """Idempotent: create per-company system roles with default permissions."""
    perms = ensure_system_permissions(CompanyPermission)
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
    return admin_role, member_role
