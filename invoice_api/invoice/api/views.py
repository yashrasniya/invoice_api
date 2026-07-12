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
from invoice_api.permissions import HasFeature, HasMethodPermission
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


class InvoiceView(ListAPIView):
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated, HasMethodPermission]
    required_permissions_map = {'GET': 'invoice.view',
                                'POST': 'invoice.create',
                                'DELETE': 'invoice.delete'}
    pagination_class = pagination.PageNumberPagination
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


    def get_queryset(self):
        qs = super().get_queryset()
        # company-wide read: members with invoice.view see all company invoices
        qs = qs.filter(user_scope_q(self.request))
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
        month_count = Invoice.objects.filter(
            user__user_company=getattr(request, 'company', None),
            date__year=today.year, date__month=today.month).count()
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

class Invoice_update(APIView):
    permission_classes = [IsAuthenticated, HasMethodPermission]
    required_permissions_map = {'POST': 'invoice.update'}

    def post(self, request, id, *args, **kwargs):
        obj = Invoice.objects.filter(user_scope_q(request), id=id)
        if not obj.exists():
            return Response({'message': 'id not found'}, status=status.HTTP_404_NOT_FOUND)
        print(request.data)
        serializer = InvoiceSerializer(obj.first(), data=request.data)

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
    template.manage permission."""
    serializer_class = new_product_in_frontendSerializer
    permission_classes = [IsAuthenticated, HasMethodPermission]
    required_permissions_map = {'POST': 'template.manage'}

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
    permission_classes = [IsAuthenticated, HasMethodPermission]
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
    permission_classes = [AllowAny]
    def get(self,request,format=None,*args, **kwargs):
        if not request.GET.get("id"):return Response({"status":400},400)
        qs = Invoice.objects.filter(user_scope_q(request), id__in=request.GET.get('id').split(','))
        return  pdf_generator(qs,request,template_id=request.GET.get("template_id",None))


class BulkExport(APIView):
    # subscription gate: bulk export is part of advanced reporting
    permission_classes = [IsAuthenticated, HasFeature.with_code('advanced_reports')]

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


