"""
Audit logging & cache invalidation for the authz/subscription system.

- Version-key invalidation: any role/group/permission/mapping change bumps
  `perm_ver:{company_id}` (covers post_save, post_delete AND m2m_changed).
- Invalidation is wrapped in transaction.on_commit so a concurrent request
  cannot re-cache pre-commit data.
- AuditLog actor comes from current_user_ctx (set by tenant middleware).
"""
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.cache import cache
from django.db import transaction
from django.db.models.signals import m2m_changed, post_delete, post_save, pre_save
from django.dispatch import receiver

from invoice_api.middleware import bump_perm_version as _bump_now, current_user_ctx

from .models import (AuditLog, CompanyGroup, CompanyPermission, CompanyRole,
                     User, UserCompanies, UserDirectPermission)
from .authz_seed import COMPANY_ADMIN_ROLE, ensure_company_roles


def bump_perm_version(company_id):
    """One INCR invalidates every user's cached permissions for the company."""
    transaction.on_commit(lambda: _bump_now(company_id))


_audit_muted = ContextVar('audit_muted', default=False)


@contextmanager
def audit_muted():
    """Skip audit rows while a company is being hard-deleted: they would point at a company that no longer exists."""
    token = _audit_muted.set(True)
    try:
        yield
    finally:
        _audit_muted.reset(token)


def audit(company, action, resource_type, resource_id, previous=None, new=None):
    if _audit_muted.get():
        return
    try:
        AuditLog.objects.create(
            company=company,
            user=current_user_ctx.get(),  # real actor from request context
            action=action, resource_type=resource_type,
            resource_id=str(resource_id), previous_data=previous, new_data=new,
        )
    except Exception:
        import logging
        logging.getLogger(__name__).exception("audit log write failed")


# ---- Role / Group / Permission saves & deletes ----

@receiver(pre_save, sender=CompanyRole)
def role_snapshot(sender, instance, **kwargs):  # previous_data
    if instance.pk:
        old = sender.objects.filter(pk=instance.pk).values('name', 'description').first()
        instance._previous = old


@receiver(post_save, sender=CompanyRole)
def on_role_save(sender, instance, created, **kwargs):
    if instance.company_id:
        bump_perm_version(instance.company_id)
    audit(instance.company, 'CREATE' if created else 'UPDATE', 'ROLE', instance.id,
          previous=getattr(instance, '_previous', None),
          new={'name': instance.name, 'description': instance.description})


@receiver(post_save, sender=CompanyGroup)
def on_group_save(sender, instance, created, **kwargs):
    if instance.company_id:
        bump_perm_version(instance.company_id)
    audit(instance.company, 'CREATE' if created else 'UPDATE', 'GROUP', instance.id,
          new={'name': instance.name, 'description': instance.description})


@receiver(post_save, sender=CompanyPermission)
def on_permission_save(sender, instance, created, **kwargs):
    if instance.company_id:
        bump_perm_version(instance.company_id)
    audit(instance.company, 'CREATE' if created else 'UPDATE', 'PERMISSION', instance.id,
          new={'name': instance.name, 'code': instance.code})


@receiver(post_delete, sender=CompanyRole)  # deletes must invalidate too
@receiver(post_delete, sender=CompanyGroup)
@receiver(post_delete, sender=CompanyPermission)
def on_authz_delete(sender, instance, **kwargs):
    if getattr(instance, 'company_id', None):
        bump_perm_version(instance.company_id)
    audit(getattr(instance, 'company', None), 'DELETE', sender.__name__.upper(), instance.id,
          previous={'name': getattr(instance, 'name', str(instance))})


# ---- M2M changes: THE main mutation path ----

def on_authz_m2m(sender, instance, action, **kwargs):
    if action in ('post_add', 'post_remove', 'post_clear') and getattr(instance, 'company_id', None):
        bump_perm_version(instance.company_id)
        audit(instance.company, 'UPDATE', type(instance).__name__.upper(), instance.id,
              new={'m2m': sender.__name__, 'action': action,
                   'ids': list(kwargs.get('pk_set') or [])})


for _field in (CompanyRole.permissions, CompanyRole.users,
               CompanyGroup.users, CompanyGroup.roles, CompanyGroup.permissions):
    m2m_changed.connect(on_authz_m2m, sender=_field.through)


# ---- Direct permissions ----

@receiver(post_save, sender=UserDirectPermission)
@receiver(post_delete, sender=UserDirectPermission)
def on_direct_permission_change(sender, instance, **kwargs):
    bump_perm_version(instance.company_id)
    created = kwargs.get('created', None)
    action = 'REVOKE' if created is None else ('ASSIGN' if instance.is_granted else 'DENY')
    audit(instance.company, action, 'PERMISSION', instance.permission_id,
          new={'user': instance.user.username, 'permission': instance.permission.code,
               'is_granted': instance.is_granted})


# ---- Bootstrap for companies/admins created after the seed migration ----

@receiver(post_save, sender=UserCompanies)
def on_company_created(sender, instance, created, **kwargs):
    if not created:
        return

    def _bootstrap():
        # default system roles for the new tenant
        ensure_company_roles(CompanyRole, CompanyPermission, instance)
        # 15-day Pro trial (no card) for a brand-new tenant, else the default Free plan
        try:
            from companies.trial import start_trial_or_free
            start_trial_or_free(instance)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("company subscription bootstrap failed")

    transaction.on_commit(_bootstrap)


@receiver(post_save, sender=User)
def sync_company_admin_role(sender, instance, **kwargs):
    """Keep legacy `is_company_admin` boolean in sync with the Company Admin
    role during the transition period."""
    if not instance.user_company_id:
        return

    def _sync():
        try:
            admin_role, _ = ensure_company_roles(
                CompanyRole, CompanyPermission, instance.user_company)
            has_role = admin_role.users.filter(pk=instance.pk).exists()
            if instance.is_company_admin and not has_role:
                admin_role.users.add(instance)
            elif not instance.is_company_admin and has_role:
                admin_role.users.remove(instance)
        except Exception:
            import logging
            logging.getLogger(__name__).exception("company admin role sync failed")

    transaction.on_commit(_sync)


# ---- Subscriptions & plan features ----

def register_company_signals():
    """Deferred registration for companies models (avoids circular imports)."""
    from companies.models import CompanySubscription, PlanFeature

    @receiver(post_save, sender=CompanySubscription)
    @receiver(post_delete, sender=CompanySubscription)
    def on_subscription_change(sender, instance, **kwargs):
        transaction.on_commit(
            lambda: cache.delete(f"company_sub:{instance.company_id}"))
        audit(instance.company, 'UPDATE', 'SUBSCRIPTION', instance.id,
              new={'plan': instance.subscription_plan.code, 'status': instance.status})

    @receiver(post_save, sender=PlanFeature)  # plan feature edits
    @receiver(post_delete, sender=PlanFeature)
    def on_plan_feature_change(sender, instance, **kwargs):
        def _clear():
            cache.delete(f"plan_features:{instance.subscription_plan_id}")
            cache.delete(f"plan_limits:{instance.subscription_plan_id}:{instance.feature.code}")
        transaction.on_commit(_clear)
