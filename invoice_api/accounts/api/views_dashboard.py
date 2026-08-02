"""
`dashboard/` — the widgets below the KPI header.

Split out from `user_info/` on purpose: the KPI cards are cheap aggregates
and should paint immediately, while these lists (trend, recent activity,
low stock) are heavier and can arrive a beat later.

Every section is gated on the permission/feature that owns the underlying
page, so a user who cannot open Inventory never sees a stock widget.
"""
from datetime import date

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from invoice.models import Invoice
from invoice_api.dashboard import (
    gst_due_dates, monthly_trend, payment_method_split, period_bounds,
    top_customers,
)
from invoice_api.scoping import user_scope_q

RECENT_LIMIT = 6
LOW_STOCK_LIMIT = 5


class Dashboard(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        perms = set(getattr(request, 'permissions', None) or set())
        feats = set(getattr(request, 'features', None) or set())
        today = date.today()

        payload = {
            'trend': [], 'recent_invoices': [], 'top_customers': [],
            'low_stock': [], 'payment_methods': [],
            'gst_due': gst_due_dates(today),
        }

        if 'invoice.view' in perms:
            rng = request.query_params.get('range') or 'this_month'
            (start, end), _prev, _label = period_bounds(rng, today)

            sales = Invoice.objects.filter(user_scope_q(request),
                                           invoice_type='sales')

            payload['trend'] = monthly_trend(sales, today, months=6)
            payload['top_customers'] = top_customers(sales, start, end)
            payload['recent_invoices'] = self._recent(sales)
            payload['payment_methods'] = payment_method_split(
                self._payments(request), start, end)

        # same gate as the Inventory page itself
        if 'inventory.manage' in perms and 'inventory' in feats:
            payload['low_stock'] = self._low_stock(request)

        return Response(payload)

    # ------------------------------------------------------------------

    def _payments(self, request):
        """Company's received payments, scoped the same way invoices are."""
        from invoice.models import Payment

        company = getattr(request, 'company', None)
        if company:
            return Payment.objects.filter(company=company)
        return Payment.objects.filter(user=request.user)

    def _recent(self, sales):
        rows = (sales.select_related('receiver')
                     .order_by('-date', '-id')[:RECENT_LIMIT])
        return [{
            'id': inv.id,
            'invoice_number': inv.invoice_number or f'#{inv.id}',
            'customer': (inv.receiver.name if inv.receiver else 'Walk-in'),
            'date': inv.date.isoformat() if inv.date else None,
            'total': round(float(inv.total_final_amount or 0)),
            'payment_status': inv.payment_status,
        } for inv in rows]

    def _low_stock(self, request):
        from django.db.models import F
        from inventory.models import Product

        # `request.company` is a SimpleLazyObject, so it is never literally
        # None — truthiness is what actually resolves it. Without a tenant we
        # show nothing rather than risk another org's stock.
        company = getattr(request, 'company', None)
        if not company:
            return []

        rows = (Product.objects.filter(company=company,
                                       current_stock__lte=F('reorder_level'))
                  .order_by('current_stock')[:LOW_STOCK_LIMIT])
        return [{
            'id': p.id,
            'name': p.name,
            'sku': p.sku,
            'current_stock': p.current_stock,
            'reorder_level': p.reorder_level,
        } for p in rows]
