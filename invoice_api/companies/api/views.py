from decimal import Decimal

from django.db.models import Count, DecimalField, Max, Q, Sum
from django.db.models.functions import Coalesce
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import status, pagination, filters
from rest_framework.authentication import TokenAuthentication
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from invoice_api.permissions import HasMethodPermission
from invoice_api.scoping import user_scope_q

from companies.models import Customers, Vendor
from invoice.models import CreditDebitNote, Invoice, Payment
from ..serializers import (CompanySerializer, CustomerStatsSerializer, VendorSerializer,
                           VendorStatsSerializer)

class MyPaginator( pagination.PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 1000


#: plan feature and permission that unlock the per-customer billing stats
STATS_FEATURE = 'advanced_reports'
STATS_PERMISSION = 'report.view'


def annotate_customer_stats(queryset, request):
    """Annotate each customer with what has been billed to them.

    Counts only *sales* invoices, matching how the customer ledger defines a
    customer's transactions (`invoice_api.ledger.party_filters`), so the two
    screens can never disagree.

    Two filters on the join are load-bearing:

    * `is_deleted=False` — `SoftDeleteModel` sets
      `base_manager_name = 'all_objects'`, so a reverse join sees deleted
      invoices and a soft-deleted bill would keep inflating the total.
    * the company scope — a customer must never report an invoice raised
      outside the requester's company.
    """
    sales = (Q(invoice__is_deleted=False)
             & Q(invoice__invoice_type='sales')
             & user_scope_q(request, 'invoice__'))
    return queryset.annotate(
        invoice_count=Count('invoice', filter=sales),
        total_billed=Coalesce(
            Sum('invoice__total_final_amount', filter=sales),
            Decimal('0'),
            output_field=DecimalField(max_digits=20, decimal_places=2)),
        last_invoice_date=Max('invoice__date', filter=sales),
    )

# How each kind of party is matched in the ledger (`invoice_api.ledger.party_filters`):
# the invoices that belong to it, which payment direction counts against it, and
# the two ways a payment or note can name it (its own FK, or its invoice's FK).
_PARTY = {
    'customer': dict(invoice_type='sales', invoice_fk='receiver_id', own_fk='customer_id',
                     via_invoice='invoice__receiver_id', direction='received'),
    'vendor': dict(invoice_type='purchase', invoice_fk='vendor_id', own_fk='vendor_id',
                   via_invoice='invoice__vendor_id', direction='made'),
}


def party_balances(request, party_ids, kind):
    """What each of these customers owes us / what we owe each of these vendors.

    Same definition as the party ledger's all-time closing balance
    (`invoice_api.ledger`): invoices, minus payments, minus credit notes, plus
    debit notes. A payment or note belongs to a party through its own FK *or*
    through its invoice's FK (the ledger matches both), so a row is credited to
    every id it names. Done in bulk for just the ids on the page rather than as
    a SQL aggregate, because the OR across two join paths is exactly what makes
    aggregates double count.
    """
    cfg = _PARTY[kind]
    ids = set(party_ids)
    scope = user_scope_q(request)
    balance = {i: Decimal('0') for i in ids}

    billed = (Invoice.objects.filter(scope, invoice_type=cfg['invoice_type'],
                                     **{cfg['invoice_fk'] + '__in': ids})
              .values(cfg['invoice_fk']).annotate(t=Sum('total_final_amount')))
    for row in billed:
        balance[row[cfg['invoice_fk']]] += row['t'] or Decimal('0')

    own, via = cfg['own_fk'], cfg['via_invoice']

    def owners(row):
        return {row[own], row[via]} & ids

    match = Q(**{own + '__in': ids}) | Q(**{via + '__in': ids})
    for pay in (Payment.objects.filter(scope).filter(match).distinct()
                .values(own, via, 'amount', 'payment_type')):
        if pay['payment_type'] == cfg['direction']:
            for i in owners(pay):
                balance[i] -= pay['amount'] or Decimal('0')
    for note in (CreditDebitNote.objects.filter(scope).filter(match).distinct()
                 .values(own, via, 'amount', 'note_type')):
        sign = -1 if note['note_type'] == 'credit' else 1
        for i in owners(note):
            balance[i] += sign * (note['amount'] or Decimal('0'))
    return balance


def customer_balances(request, customer_ids):
    return party_balances(request, customer_ids, 'customer')


def annotate_vendor_stats(queryset, request):
    """What has been bought from each vendor: purchase invoices only (matching
    the supplier ledger), live rows only, and only within the requester's company."""
    bills = (Q(invoice__is_deleted=False) & Q(invoice__invoice_type='purchase')
             & user_scope_q(request, 'invoice__'))
    return queryset.annotate(
        invoice_count=Count('invoice', filter=bills),
        total_purchased=Coalesce(
            Sum('invoice__total_final_amount', filter=bills),
            Decimal('0'),
            output_field=DecimalField(max_digits=20, decimal_places=2)),
        last_invoice_date=Max('invoice__date', filter=bills),
    )


class StatsOptInMixin:
    """`?with_stats=1` turns on per-party billing stats, on plans that carry them.

    Opt-in because these lists also feed every dropdown in the app, and those
    have no use for an extra aggregate join. Without the plan feature the flag
    is *ignored* rather than rejected: failing the whole list closed would break
    customer / vendor selection for everyone on a cheaper plan.
    """

    def _wants_stats(self):
        request = getattr(self, 'request', None)
        if request is None:
            return False
        if request.query_params.get('with_stats') not in ('1', 'true', 'True'):
            return False
        return (STATS_FEATURE in (getattr(request, 'features', None) or set())
                and STATS_PERMISSION in (getattr(request, 'permissions', None) or set()))


class CompaniesView(StatsOptInMixin, ListAPIView):
    serializer_class = CompanySerializer
    permission_classes = [IsAuthenticated, HasMethodPermission]
    required_permissions_map = {'POST': 'customer.manage',
                                'DELETE': 'customer.manage'}
    pagination_class = MyPaginator
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    # ?id=<pk> lets a caller resolve one customer by id — the invoice list
    # needs the name behind a `?customer=<id>` deep link
    filterset_fields = ['id', 'state']
    search_fields = ['name', 'gst_number', 'phone_number']
    ordering_fields = ['id', 'name']
    ordering = ['-id']

    def get_serializer_class(self):
        return CustomerStatsSerializer if self._wants_stats() else CompanySerializer

    def get_queryset(self):
        qs = Customers.objects.filter(user_scope_q(self.request))
        # ?has_gst=1 → GST-registered customers only, ?has_gst=0 → unregistered only
        has_gst = self.request.query_params.get('has_gst')
        if has_gst in ('1', 'true', 'True'):
            qs = qs.exclude(gst_number='')
        elif has_gst in ('0', 'false', 'False'):
            qs = qs.filter(gst_number='')
        if self._wants_stats():
            qs = annotate_customer_stats(qs, self.request)
        return qs

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        if self._wants_stats():
            rows = response.data['results'] if isinstance(response.data, dict) else response.data
            balances = customer_balances(request, [r['id'] for r in rows])
            for r in rows:
                r['outstanding_balance'] = balances[r['id']]
        return response

    def post(self,request,*args,**kwargs):
        print(request.POST)
        if kwargs.get('id','') :
            if Customers.objects.filter(id=kwargs.get('id')):
                serializer = CompanySerializer(Customers.objects.get(id=kwargs.get('id')), data=request.data)
            else:
                return Response({'error':'Company id not found'}, status=status.HTTP_404_NOT_FOUND)
        else:
            serializer = CompanySerializer(data=request.data)
        if serializer.is_valid():
            print(serializer.validated_data)
            serializer.save(user=self.request.user)
            return Response(serializer.data,status=status.HTTP_200_OK)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self,request,id,*args, **kwargs):

        if not Customers.objects.filter(id=self.kwargs.get('id')):
            return Response({'error': 'id not found'}, status=status.HTTP_400_BAD_REQUEST)
        Customers.objects.get(id=self.kwargs.get('id')).delete()
        return Response({"message":"delete successfully"},status=status.HTTP_204_NO_CONTENT)


class VendorView(StatsOptInMixin, ListAPIView):
    serializer_class = VendorSerializer
    permission_classes = [IsAuthenticated, HasMethodPermission]
    required_permissions_map = {'POST': 'vendor.manage',
                                'DELETE': 'vendor.manage'}
    pagination_class = MyPaginator
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    # ?id=<pk> resolves one vendor by id (the invoice list names the vendor
    # behind a `?vendor=<id>` deep link); ?state= is an exact match
    filterset_fields = ['id', 'state']
    search_fields = ['name', 'gst_number', 'phone_number']
    ordering_fields = ['id', 'name']
    ordering = ['-id']

    def get_serializer_class(self):
        return VendorStatsSerializer if self._wants_stats() else VendorSerializer

    def get_queryset(self):
        qs = Vendor.objects.filter(user_scope_q(self.request))
        # ?has_gst=1 → GST-registered vendors only, ?has_gst=0 → unregistered only
        has_gst = self.request.query_params.get('has_gst')
        if has_gst in ('1', 'true', 'True'):
            qs = qs.exclude(gst_number='')
        elif has_gst in ('0', 'false', 'False'):
            qs = qs.filter(gst_number='')
        if self._wants_stats():
            qs = annotate_vendor_stats(qs, self.request)
        return qs

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        if self._wants_stats():
            rows = response.data['results'] if isinstance(response.data, dict) else response.data
            balances = party_balances(request, [r['id'] for r in rows], 'vendor')
            for r in rows:
                r['outstanding_balance'] = balances[r['id']]
        return response

    def post(self,request,*args,**kwargs):
        print(request.POST)
        if kwargs.get('id','') :
            if Vendor.objects.filter(id=kwargs.get('id')):
                serializer = VendorSerializer(Vendor.objects.get(id=kwargs.get('id')), data=request.data)
            else:
                return Response({'error':'Vendor id not found'}, status=status.HTTP_404_NOT_FOUND)
        else:
            serializer = VendorSerializer(data=request.data)
        if serializer.is_valid():
            print(serializer.validated_data)
            serializer.save(user=self.request.user)
            return Response(serializer.data,status=status.HTTP_200_OK)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self,request,id,*args, **kwargs):

        if not Vendor.objects.filter(id=self.kwargs.get('id')):
            return Response({'error': 'id not found'}, status=status.HTTP_400_BAD_REQUEST)
        Vendor.objects.get(id=self.kwargs.get('id')).delete()
        return Response({"message":"delete successfully"},status=status.HTTP_204_NO_CONTENT)