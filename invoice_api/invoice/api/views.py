import datetime
import io
import logging

from django.db.models import Q
from django.http import FileResponse
from rest_framework import status, viewsets, pagination
from rest_framework.generics import ListAPIView, RetrieveUpdateAPIView
from rest_framework.permissions import IsAuthenticated,AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import filters, pagination
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from companies.models import Companies
from companies.serializers import CompanySerializer
from invoice.models import Invoice, Product, new_product_in_frontend, Product_properties
from submit import Submit
from yaml_manager.models import Yaml
from yaml_reader import YamalReader, FillValue
from ..export import pdf_generator, csv_generator
from ..serializers import InvoiceSerializer, new_product_in_frontendSerializer, ProductSerializer, \
    Product_propertiesSerializer, InvoiceSerializerForPDF

logger = logging.getLogger(__name__)


class InvoiceView(ListAPIView):
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = pagination.PageNumberPagination
    queryset = Invoice.objects.filter()

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    # Exact field filtering (e.g., ?status=paid)
    filterset_fields = ['receiver', 'date','id']

    # Search (partial match, e.g., ?search=ABC)
    search_fields = ['invoice_number', 'receiver__name',]

    # Ordering (e.g., ?ordering=-invoice_date)
    ordering_fields = ['date', 'total_final_amount','gst_final_amount']
    ordering = ['-date']


    def get_queryset(self):
        qs = super().get_queryset()
        qs = qs.filter(user = self.request.user)
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
        print(request.POST)
        serializer = InvoiceSerializer(data=request.data)
        if serializer.is_valid():
            print(serializer.validated_data)
            serializer.save(user=self.request.user)
            return Response(serializer.data)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def delete(self,request,*args, **kwargs):

        if not Invoice.objects.filter(id=self.request.query_params.get('id')):
            return Response({'error': 'id not found'}, status=status.HTTP_400_BAD_REQUEST)
        Invoice.objects.get(id=self.request.query_params.get('id')).delete()
        return Response({"message":"delete successfully"},status=status.HTTP_204_NO_CONTENT)

class Invoice_update(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, id, *args, **kwargs):
        obj = Invoice.objects.filter(id=id,user=request.user)
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
    permission_classes = [IsAuthenticated]

    def post(self, request,id, action):
        print(id,action,request.data.get('product_id',''))
        if not action in ['add', 'delete']:
            return Response({'message': 'invalid action'}, status=status.HTTP_400_BAD_REQUEST)
        obj = Invoice.objects.filter(id=id)
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
    serializer_class = new_product_in_frontendSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if self.kwargs.get('id',''):
            return new_product_in_frontend.objects.filter(id=self.kwargs.get('id',''),user=self.request.user)
        return new_product_in_frontend.objects.filter(user=self.request.user)

    def post(self, request, *args, **kwargs):
        serializer = new_product_in_frontendSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user=self.request.user)
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class new_product_in_frontend_update_view(APIView):
    permission_classes = [IsAuthenticated]
    def get_queryset(self):
        if not self.kwargs.get('id',''):
            return Response({'error': 'id is required'}, status=status.HTTP_400_BAD_REQUEST)
        if not new_product_in_frontend.objects.filter(id=self.kwargs.get('id')):
            return Response({'error': 'id not found'}, status=status.HTTP_400_BAD_REQUEST)
        return new_product_in_frontend.objects.get(id=self.kwargs.get('id'))

    def post(self,request,*args, **kwargs):
        serializer = new_product_in_frontendSerializer(self.get_queryset(),data=request.data)
        if serializer.is_valid():
            serializer.save(user=self.request.user)
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self,request,id,*args, **kwargs):

        if not new_product_in_frontend.objects.filter(id=self.kwargs.get('id')):
            return Response({'error': 'id not found'}, status=status.HTTP_400_BAD_REQUEST)
        new_product_in_frontend.objects.get(id=self.kwargs.get('id')).delete()
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
        qs = Invoice.objects.filter(id__in=request.GET.get('id').split(','), user=request.user)
        return  pdf_generator(qs,request)


class BulkExport(APIView):
    permission_classes = [IsAuthenticated]

    def post(self,request):
        # Extract values from request data
        search = request.data.get("s", "").strip()
        customers = request.data.get("customer", [])  # This will be a list
        date_from = request.data.get("date_from", "").strip()
        date_to = request.data.get("date_to", "").strip()
        type = request.data.get("type", "PDF").strip()

        # Start with base queryset
        queryset = Invoice.objects.all()

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
        if type =="PDF":
            return pdf_generator(queryset, request)
        else:
            return csv_generator(queryset,request)

