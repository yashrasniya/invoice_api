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
from ..serializers import CompanySerializer, CustomerStatsSerializer, VendorSerializer

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

class CompaniesView(ListAPIView):
    serializer_class = CompanySerializer
    permission_classes = [IsAuthenticated, HasMethodPermission]
    required_permissions_map = {'POST': 'customer.manage',
                                'DELETE': 'customer.manage'}
    pagination_class = MyPaginator
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    # ?id=<pk> lets a caller resolve one customer by id — the invoice list
    # needs the name behind a `?customer=<id>` deep link
    filterset_fields = ['id']
    search_fields = ['name']
    ordering_fields = ['id', 'name']
    ordering = ['-id']

    def _wants_stats(self):
        """Whether to attach per-customer billing stats to this response.

        Opt-in via `?with_stats=1`, because this list also feeds every
        customer dropdown in the app and those have no use for an extra
        aggregate join.

        Without the plan feature the flag is *ignored* rather than rejected:
        failing the whole list closed would break customer selection for
        everyone on a cheaper plan.
        """
        request = getattr(self, 'request', None)
        if request is None:
            return False
        if request.query_params.get('with_stats') not in ('1', 'true', 'True'):
            return False
        return (STATS_FEATURE in (getattr(request, 'features', None) or set())
                and STATS_PERMISSION in (getattr(request, 'permissions', None) or set()))

    def get_serializer_class(self):
        return CustomerStatsSerializer if self._wants_stats() else CompanySerializer

    def get_queryset(self):
        qs = Customers.objects.filter(user_scope_q(self.request))
        if self._wants_stats():
            qs = annotate_customer_stats(qs, self.request)
        return qs

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


class VendorView(ListAPIView):
    serializer_class = VendorSerializer
    permission_classes = [IsAuthenticated, HasMethodPermission]
    required_permissions_map = {'POST': 'vendor.manage',
                                'DELETE': 'vendor.manage'}
    pagination_class = MyPaginator
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name']
    ordering_fields = ['id', 'name']
    ordering = ['-id']

    def get_queryset(self):
        return Vendor.objects.filter(user_scope_q(self.request))

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