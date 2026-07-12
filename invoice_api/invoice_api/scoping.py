"""
Company scoping for business models still keyed to `user` (pre-Phase-5).

Invoices, customers, vendors etc. carry a `user` FK ("created by"), so a
plain `filter(user=request.user)` hides other company members' records.
`user_scope_q(request)` widens reads to the whole company while keeping a
safe fallback to the requesting user when no company is resolved.
"""
from django.db.models import Q


def user_scope_q(request):
    """Q filter: rows created by any member of the requester's company."""
    company = getattr(request, 'company', None)
    if company is not None:
        return Q(user__user_company=company)
    return Q(user=request.user)
