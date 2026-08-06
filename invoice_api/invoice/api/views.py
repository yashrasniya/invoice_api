import datetime
import io
import logging

from django.db.models import Q
from django.http import FileResponse
from rest_framework import status, viewsets, pagination
from rest_framework.generics import ListAPIView, RetrieveUpdateAPIView, UpdateAPIView
from rest_framework.permissions import IsAuthenticated,AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import filters, pagination
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from invoice_api.limits import enforce_limit
from invoice_api.permissions import HasFeature, HasMethodFeature, HasMethodPermission
from invoice_api.scoping import company_config_owner, user_scope_q

from companies.models import Customers
from companies.serializers import CompanySerializer
from invoice.models import Invoice, Product, new_product_in_frontend, Product_properties, CustomField
from submit import Submit
from yaml_manager.models import Yaml
from yaml_reader import YamalReader, FillValue
from ..export import pdf_generator, csv_generator, pdf_data_generator
from ..serializers import InvoiceSerializer, new_product_in_frontendSerializer, ProductSerializer, \
    Product_propertiesSerializer, InvoiceSerializerForPDF, CustomFieldSerializer


logger = logging.getLogger(__name__)


class InvoicePaginator(pagination.PageNumberPagination):
    page_size = 15
    page_size_query_param = 'page_size'
    max_page_size = 1000

class InvoiceView(ListAPIView):
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated, HasMethodPermission]
    required_permissions_map = {'GET': 'invoice.view',
                                'POST': 'invoice.create',
                                'DELETE': 'invoice.delete'}
    pagination_class = InvoicePaginator
    queryset = Invoice.objects.filter()

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    # Exact field filtering (e.g., ?status=paid)
    filterset_fields = ['receiver', 'date','id', 'invoice_type',
                        'payment_status', 'payment_method']

    # Search (partial match, e.g., ?search=ABC)
    search_fields = ['invoice_number', 'receiver__name',]

    # Ordering (e.g., ?ordering=-invoice_date)
    ordering_fields = ['date', 'total_final_amount','gst_final_amount']
    ordering = ['-date']


    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context

    def get_queryset(self):
        qs = super().get_queryset()
        # company-wide read: members with invoice.view see all company invoices
        qs = qs.filter(user_scope_q(self.request))
        # `payment_status` is an exact filter; the dashboard's Outstanding and
        # Overdue cards need sets it can't express, so they deep-link with
        # ?status_group=open / =overdue. Both use the same helper the cards
        # are computed from, so the list and the card always agree.
        status_group = self.request.query_params.get('status_group')
        if status_group in ('open', 'overdue'):
            from invoice_api.dashboard import open_invoices_qs
            qs = open_invoices_qs(qs)
            if status_group == 'overdue':
                qs = qs.filter(is_overdue=True)
        date_from = self.request.query_params.get('date_from')
        date_to = self.request.query_params.get('date_to')
        customers = self.request.query_params.get('customer')
        if customers:
            customer_list = customers.split(',')
            qs = qs.filter(receiver__in=customer_list)
        if date_from and date_to:
            qs = qs.filter(date__range=[date_from, date_to])
        elif date_from:
            qs = qs.filter(date__gte=date_from)
        elif date_to:
            qs = qs.filter(date__lte=date_to)
        return qs


    def post(self, request, *args, **kwargs):
        # plan limit: invoices created this month across the whole company
        today = datetime.date.today()
        inv_type = request.data.get('invoice_type', 'sales')
        month_count = Invoice.objects.filter(
            user_scope_q(request),
            invoice_type=inv_type,
            date__year=today.year, date__month=today.month).count()
            
        if inv_type == 'purchase':
            enforce_limit(request, 'purchases_invoice', 'purchases_per_month', month_count)
        else:
            enforce_limit(request, 'invoicing', 'invoices_per_month', month_count)

        serializer = InvoiceSerializer(data=request.data)
        if serializer.is_valid():
            print(serializer.validated_data)
            serializer.save(user=self.request.user)
            return Response(serializer.data)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def delete(self,request,*args, **kwargs):
        # scoped to the company — no cross-tenant deletes
        qs = Invoice.objects.filter(user_scope_q(request),
                                    id=self.request.query_params.get('id'))
        if not qs.exists():
            return Response({'error': 'id not found'}, status=status.HTTP_400_BAD_REQUEST)
        qs.first().delete()
        return Response({"message":"delete successfully"},status=status.HTTP_204_NO_CONTENT)


from invoice.models import Payment, CreditDebitNote

class LedgerAPIView(APIView):
    """Party ledger + receivables analysis.

    Response is a superset of the old one — `opening_balance`,
    `closing_balance`, `transactions`, `total_sales`, `total_receipts`,
    `total_purchases` and `total_payments_made` are unchanged, so the
    Supplier Ledger page keeps working.
    """
    permission_classes = [IsAuthenticated, HasMethodPermission, HasFeature.with_code('advanced_reports')]
    required_permissions_map = {'GET': 'report.view'}

    PERIODS = ('this_month', 'last_month', 'this_quarter', 'this_fy', 'all_time')

    def get(self, request, entity_type, entity_id):
        from decimal import Decimal

        from companies.models import Customers, Vendor
        from invoice_api import ledger as L
        from invoice_api.gst import gst_period_bounds

        if entity_type not in ('customer', 'vendor'):
            return Response({'error': 'Invalid entity type'}, status=400)

        today = datetime.date.today()
        period = request.query_params.get('period')
        date_from = request.query_params.get('start_date')
        date_to = request.query_params.get('end_date')

        # ── period resolution (dates used to 500 on anything malformed) ──
        if period == 'all_time':
            start, end, label = datetime.date(1970, 1, 1), today, 'All time'
        elif period in self.PERIODS:
            start, end, label = gst_period_bounds(period, today)
        elif date_from or date_to:
            if not (date_from and date_to):
                return Response(
                    {'error': 'Both start_date and end_date are required.'}, status=400)
            try:
                start = datetime.datetime.strptime(date_from, '%Y-%m-%d').date()
                end = datetime.datetime.strptime(date_to, '%Y-%m-%d').date()
            except ValueError:
                return Response(
                    {'error': 'Dates must be in YYYY-MM-DD format.'}, status=400)
            if end < start:
                return Response(
                    {'error': 'end_date cannot be before start_date.'}, status=400)
            label = f'{start} to {end}'
        else:
            start, end, label = gst_period_bounds('this_month', today)
            period = 'this_month'

        # ── scope ──
        scope = user_scope_q(request)
        model = Customers if entity_type == 'customer' else Vendor
        party = model.objects.filter(scope, id=entity_id).first()
        if party is None:
            return Response({'error': f'{entity_type.title()} not found.'}, status=404)

        f = L.party_filters(entity_type, entity_id)
        # `.distinct()` because the payment/note filters OR across an
        # invoice join, which can otherwise duplicate rows
        invoices = Invoice.objects.filter(scope).filter(f['invoice'])
        payments = Payment.objects.filter(scope).filter(f['payment']).distinct()
        notes = CreditDebitNote.objects.filter(scope).filter(f['note']).distinct()

        opening = L.opening_balance(entity_type, invoices, payments, notes, start)

        in_period = dict(date__gte=start, date__lte=end)
        cur_invoices = list(invoices.filter(**in_period))
        cur_payments = list(payments.filter(**in_period))
        cur_notes = list(notes.filter(**in_period))

        rows = L.build_transactions(entity_type, cur_invoices, cur_payments, cur_notes)
        closing = L.apply_running_balance(rows, opening, entity_type)

        # ── analysis (all-time, not window-limited: what is owed is owed) ──
        paid_by_invoice = {}
        direction = 'received' if entity_type == 'customer' else 'made'
        for pay in payments:
            if pay.invoice_id and pay.payment_type == direction:
                paid_by_invoice[pay.invoice_id] = (
                    paid_by_invoice.get(pay.invoice_id, Decimal('0'))
                    + Decimal(str(pay.amount or 0)))

        open_rows = L.outstanding_by_invoice(invoices, paid_by_invoice, today)
        buckets = L.ageing(open_rows)
        behaviour = L.payment_behaviour(invoices, payments, today)
        trend = L.monthly_activity(invoices, payments, months=6, today=today)
        lifetime = L.lifetime_totals(entity_type, list(invoices), list(payments), notes)

        def num(v):
            return float(v or 0)

        totals = {
            'total_sales': sum(num(r['debit']) for r in rows if r['vch_type'] == 'Sales'),
            'total_receipts': sum(num(r['credit']) for r in rows if r['vch_type'] == 'Receipt'),
            'total_purchases': sum(num(r['credit']) for r in rows if r['vch_type'] == 'Purchase'),
            'total_payments_made': sum(num(r['debit']) for r in rows if r['vch_type'] == 'Payment'),
        }

        return Response({
            # ── unchanged contract ──
            'opening_balance': num(opening),
            'closing_balance': num(closing),
            'transactions': [
                {**r,
                 'debit': num(r['debit']), 'credit': num(r['credit']),
                 'balance': num(r['balance'])}
                for r in rows
            ],
            **totals,

            # ── added ──
            'entity_type': entity_type,
            'period': period or 'custom',
            'period_label': label,
            'start_date': start.isoformat(),
            'end_date': end.isoformat(),

            'party': {
                'id': party.id,
                'name': party.name,
                'legal_name': getattr(party, 'legal_name', '') or '',
                'gst_number': getattr(party, 'gst_number', '') or '',
                'email': getattr(party, 'email', '') or '',
                'phone_number': getattr(party, 'phone_number', '') or '',
                'city': getattr(party, 'city', '') or '',
                'state': getattr(party, 'state', '') or '',
                'state_code': getattr(party, 'state_code', None),
                'address': getattr(party, 'address', '') or '',
            },

            'outstanding_total': num(sum((r['due'] for r in open_rows), Decimal('0'))),
            'outstanding_count': len(open_rows),
            'ageing': [{**b, 'amount': num(b['amount'])} for b in buckets],
            'ageing_basis': 'days since invoice date (no due-date column exists)',
            'open_invoices': [
                {**r, 'billed': num(r['billed']), 'paid': num(r['paid']),
                 'due': num(r['due'])}
                for r in open_rows[:25]
            ],

            'behaviour': behaviour,
            'trend': [{**t, 'billed': num(t['billed']),
                       'collected': num(t['collected'])} for t in trend],
            'lifetime': {
                **lifetime,
                'billed': num(lifetime['billed']),
                'gst': num(lifetime['gst']),
                'settled': num(lifetime['settled']),
                'largest_invoice': num(lifetime['largest_invoice']),
                'first_invoice_date': (lifetime['first_invoice_date'].isoformat()
                                       if lifetime['first_invoice_date'] else None),
            },
        })


class Invoice_update(APIView):
    permission_classes = [IsAuthenticated, HasMethodPermission]
    required_permissions_map = {'POST': 'invoice.update'}

    def post(self, request, id, *args, **kwargs):
        obj = Invoice.objects.filter(user_scope_q(request), id=id)
        if not obj.exists():
            return Response({'message': 'id not found'}, status=status.HTTP_404_NOT_FOUND)
        print(request.data)
        serializer = InvoiceSerializer(obj.first(), data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save()
            print(serializer.data.get("date"))
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class Invoice_product_action(APIView):
    permission_classes = [IsAuthenticated, HasMethodPermission]
    required_permissions_map = {'POST': 'invoice.update'}

    def post(self, request,id, action):
        print(id,action,request.data.get('product_id',''))
        if not action in ['add', 'delete']:
            return Response({'message': 'invalid action'}, status=status.HTTP_400_BAD_REQUEST)
        obj = Invoice.objects.filter(user_scope_q(request), id=id)
        if not obj.exists():
            return Response({'message': 'id not found'}, status=status.HTTP_404_NOT_FOUND)
        if not request.data.get('product_id',''):
            return Response({'message': 'product_id not found'}, status=status.HTTP_404_NOT_FOUND)
        if not Product.objects.filter(id=request.data.get('product_id')):
            return Response({'message': 'product_id not found in db'}, status=status.HTTP_404_NOT_FOUND)
        if action == 'add':
            obj.first().products.add(request.data.get('product_id'))
        elif action == 'delete':
            obj.first().products.remove(request.data.get('product_id'))

        return Response({'message': 'success'}, status=status.HTTP_200_OK)


class new_product_in_frontend_view(ListAPIView):
    """Company-wide bill-field configuration. Everyone in the company reads
    the same set (owned by the company's first admin); editing requires the
    template.manage permission.

    Reads stay open on every plan – the same convention as yaml_manager – because
    the bill columns are needed to render a bill and to fill in the line items of
    an extracted purchase invoice. Gating GET behind template_designer made every
    imported row come back empty on plans without that feature."""
    serializer_class = new_product_in_frontendSerializer
    permission_classes = [IsAuthenticated, HasMethodPermission, HasMethodFeature]
    required_permissions_map = {'POST': 'template.manage'}
    required_features_map = {'POST': 'template_designer'}

    def get_queryset(self):
        owner = company_config_owner(self.request)
        if self.kwargs.get('id',''):
            return new_product_in_frontend.objects.filter(id=self.kwargs.get('id',''),user=owner)
        return new_product_in_frontend.objects.filter(user=owner)

    def post(self, request, *args, **kwargs):
        serializer = new_product_in_frontendSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user=company_config_owner(request))
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class new_product_in_frontend_update_view(APIView):
    permission_classes = [IsAuthenticated, HasMethodPermission, HasFeature.with_code('template_designer')]
    required_permissions_map = {'POST': 'template.manage',
                                'DELETE': 'template.manage'}

    def get_queryset(self):
        # scoped to the company's shared config set — no foreign ids
        owner = company_config_owner(self.request)
        if not self.kwargs.get('id',''):
            return Response({'error': 'id is required'}, status=status.HTTP_400_BAD_REQUEST)
        if not new_product_in_frontend.objects.filter(id=self.kwargs.get('id'), user=owner):
            return Response({'error': 'id not found'}, status=status.HTTP_400_BAD_REQUEST)
        return new_product_in_frontend.objects.get(id=self.kwargs.get('id'), user=owner)

    def post(self,request,*args, **kwargs):
        serializer = new_product_in_frontendSerializer(self.get_queryset(),data=request.data)
        if serializer.is_valid():
            serializer.save(user=company_config_owner(request))
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self,request,id,*args, **kwargs):
        owner = company_config_owner(request)
        qs = new_product_in_frontend.objects.filter(id=self.kwargs.get('id'), user=owner)
        if not qs:
            return Response({'error': 'id not found'}, status=status.HTTP_400_BAD_REQUEST)
        qs.first().delete()
        return Response({"message":"delete successfully"},status=status.HTTP_204_NO_CONTENT)

class ProductViewSet(APIView):
    permission_classes = [IsAuthenticated]
    def post(self,request,*args, **kwargs):
        if kwargs.get('id',''):
            if not Product.objects.filter(id=self.kwargs.get('id')):
                return Response({'error': 'id not found'}, status=status.HTTP_400_BAD_REQUEST)

            product = ProductSerializer(Product.objects.get(id=self.kwargs.get('id')),data=request.data)
        else:
            product = ProductSerializer(data=request.data)
        if product.is_valid():
            obj=product.save()
            if request.data.get('product_properties',''):
                Product_properties_id_list=request.data.get('product_properties', '').split(',')
                for i in Product_properties_id_list:
                    if Product_properties.objects.filter(id=i).exists():
                        if request.POST.get('action','')=='delete':
                            obj.product_properties.remove(i)
                        else:
                            obj.product_properties.add(i)
            return Response(product.data)
        else:
            return Response(product.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self,request,id,*args, **kwargs):

        if not Product.objects.filter(id=self.kwargs.get('id')):
            return Response({'error': 'id not found'}, status=status.HTTP_400_BAD_REQUEST)
        Product.objects.get(id=self.kwargs.get('id')).delete()
        return Response({"message":"delete successfully"},status=status.HTTP_204_NO_CONTENT)

class ProductPropertiesViewsSet(APIView):
    permission_classes = [IsAuthenticated]

    def post(self,request,format=None,*args, **kwargs):
        Product_propertiesSerializer(data=request)
        if kwargs.get('id',''):
            if not Product_properties.objects.filter(id=self.kwargs.get('id')):
                return Response({'error': 'id not found'}, status=status.HTTP_400_BAD_REQUEST)

            product = Product_propertiesSerializer(Product_properties.objects.get(id=self.kwargs.get('id')),data=request.data)
        else:
            product = Product_propertiesSerializer(data=request.data)
        if product.is_valid():
            if  request.data.get('new_product_in_frontend') and new_product_in_frontend.objects.filter(id=request.data.get('new_product_in_frontend')):

                product.save(new_product_in_frontend=new_product_in_frontend.objects.get(id=request.data.get('new_product_in_frontend','')))

                return Response(product.data)
            else:
                if kwargs.get('id',''):
                    product.save()
                    return Response(product.data)
                else:
                    return Response({'error': 'id not found'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response(product.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self,request,id,*args, **kwargs):

        if not Product_properties.objects.filter(id=self.kwargs.get('id')):
            return Response({'error': 'id not found'}, status=status.HTTP_400_BAD_REQUEST)
        Product_properties.objects.get(id=self.kwargs.get('id')).delete()
        return Response({"message":"delete successfully"},status=status.HTTP_204_NO_CONTENT)



class PdfMaker(APIView):
    permission_classes = [IsAuthenticated]
    def get(self,request,format=None,*args, **kwargs):
        if not request.GET.get("id"):return Response({"status":400},400)
        qs = Invoice.objects.filter(user_scope_q(request), id__in=request.GET.get('id').split(','))
        return  pdf_generator(qs,request,template_id=request.GET.get("template_id",None))


class BulkExport(APIView):
    # subscription gate: bulk export is its own feature
    permission_classes = [IsAuthenticated, HasFeature.with_code('bulk_export')]

    def post(self,request):
        # Extract values from request data
        search = request.data.get("s", "").strip()
        customers = request.data.get("customer", [])  # This will be a list
        date_from = request.data.get("date_from", "").strip()
        date_to = request.data.get("date_to", "").strip()
        export_type = request.data.get("type", "PDF").strip()
        invoice_type = request.data.get("invoice_type")

        # Start with base queryset
        queryset = Invoice.objects.filter(user_scope_q(request))

        if not queryset:
            return Response({"error":"no invoice found"},status=status.HTTP_400_BAD_REQUEST)
        # Search filter (on invoice_number or receiver name)
        if search:
            queryset = queryset.filter(
                Q(invoice_number__icontains=search) |
                Q(receiver__name__icontains=search)
            )

        # Customer filter (list of IDs)
        if customers and isinstance(customers, list):
            queryset = queryset.filter(receiver_id__in=customers)

        # Date range filter
        if date_from and date_to:
            queryset = queryset.filter(date__range=[date_from, date_to])
        elif date_from:
            queryset = queryset.filter(date__gte=date_from)
        elif date_to:
            queryset = queryset.filter(date__lte=date_to)
            
        if invoice_type:
            queryset = queryset.filter(invoice_type=invoice_type)
            
        if export_type =="PDF":
            return pdf_generator(queryset, request)
        elif export_type == "PDF_DATA":
            return pdf_data_generator(queryset, request)
        else:
            return csv_generator(queryset,request)


class CustomFieldViewSet(viewsets.ModelViewSet):
    serializer_class = CustomFieldSerializer
    permission_classes = [IsAuthenticated, HasMethodPermission]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['hidden', 'field_type', 'company']
    search_fields = ['name']
    ordering_fields = ['created_time', 'name']
    ordering = ['-created_time']

    # reads open to the company; writes need template.manage
    required_permissions_map = {'POST': 'template.manage',
                                'PUT': 'template.manage',
                                'PATCH': 'template.manage',
                                'DELETE': 'template.manage'}

    def get_queryset(self):
        return CustomField.objects.filter(user=company_config_owner(self.request))

    def perform_create(self, serializer):
        serializer.save(user=company_config_owner(self.request))


