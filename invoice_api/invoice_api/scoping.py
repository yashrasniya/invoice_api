"""
Company scoping for business models still keyed to `user` (pre-Phase-5).

Invoices, customers, vendors etc. carry a `user` FK ("created by"), so a
plain `filter(user=request.user)` hides other company members' records.
`user_scope_q(request)` widens reads to the whole company while keeping a
safe fallback to the requesting user when no company is resolved.
"""
from django.db.models import Q


def user_scope_q(request, prefix=''):
    """Q filter: rows created by any member of the requester's company.

    `prefix` walks the same check across a relation, e.g.
    `user_scope_q(request, 'invoice__')` keeps a joined invoice inside the
    requester's company instead of trusting the join to stay in-tenant.
    """
    company = getattr(request, 'company', None)
    if company is not None:
        return Q(**{f'{prefix}user__user_company': company})
    return Q(**{f'{prefix}user': request.user})


def company_config_owner(request):
    """Canonical owner of company-wide configuration (UI field config,
    custom fields): the company's first admin. Every member reads and —
    with permission — writes that same set, so the whole company sees one
    consistent configuration."""
    company = getattr(request, 'company', None)
    if company is not None:
        from accounts.models import User
        # prefer the member who actually owns config rows (the company
        # creator got the default field set at signup)
        owner = (User.objects
                 .filter(user_company=company,
                         new_product_in_frontend__isnull=False)
                 .order_by('id').first())
        if owner:
            return owner
        owner = (User.objects
                 .filter(user_company=company, is_company_admin=True)
                 .order_by('id').first())
        if owner:
            return owner
    return request.user
