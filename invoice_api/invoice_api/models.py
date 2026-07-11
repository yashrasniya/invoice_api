"""
Tenant-scoped ORM base: fail-closed manager + auto-stamping abstract model.
"""
from django.db import models

from .middleware import active_company_ctx


class TenantQuerySet(models.QuerySet):
    def for_company(self, company):
        """Explicit scoping for background jobs / management commands."""
        return self.filter(company=company)


class TenantManager(models.Manager.from_queryset(TenantQuerySet)):
    def get_queryset(self):
        qs = super().get_queryset()
        company = active_company_ctx.get()
        if company is not None:
            return qs.filter(company=company)
        return qs.none()  # fail CLOSED — no context, no rows


class TenantModel(models.Model):
    company = models.ForeignKey(
        'accounts.UserCompanies', on_delete=models.CASCADE, db_index=True)

    all_objects = models.Manager()  # explicit cross-tenant access (Product Owner, admin, jobs)
    objects = TenantManager()

    class Meta:
        abstract = True
        base_manager_name = 'all_objects'  # FK traversal & internals must not be filtered

    def save(self, *args, **kwargs):
        # auto-stamp tenant on create; block cross-tenant writes
        company = active_company_ctx.get()
        if self.company_id is None and company is not None:
            self.company = company
        if company is not None and self.company_id != company.id:
            raise PermissionError("Cross-tenant write blocked")
        super().save(*args, **kwargs)
