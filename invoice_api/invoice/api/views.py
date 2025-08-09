import datetime
import io
import logging

from django.http import FileResponse
from rest_framework import status, viewsets, pagination
from rest_framework.generics import ListAPIView, RetrieveUpdateAPIView
from rest_framework.permissions import IsAuthenticated,AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from companies.models import Companies
from companies.serializers import CompanySerializer
from invoice.models import Invoice, Product, new_product_in_frontend, Product_properties
from submit import Submit
from yaml_manager.models import Yaml
from yaml_reader import YamalReader, FillValue
from ..serializers import InvoiceSerializer, new_product_in_frontendSerializer, ProductSerializer, \
    Product_propertiesSerializer, InvoiceSerializerForPDF

logger = logging.getLogger(__name__)


class InvoiceView(ListAPIView):
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = pagination.PageNumberPagination


    def get_queryset(self):
        if self.kwargs.get('id',''):
            return Invoice.objects.filter(user=self.request.user, id=self.kwargs.get('id'))
        return Invoice.objects.filter(user=self.request.user).order_by('-id')

    def post(self, request, *args, **kwargs):
        print(request.POST)
        serializer = InvoiceSerializer(data=request.data)
        if serializer.is_valid():
            print(serializer.validated_data)
            serializer.save(user=self.request.user)
            return Response(serializer.data)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    def delete(self,request,id,*args, **kwargs):

        if not Invoice.objects.filter(id=self.kwargs.get('id')):
            return Response({'error': 'id not found'}, status=status.HTTP_400_BAD_REQUEST)
        Invoice.objects.get(id=self.kwargs.get('id')).delete()
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


class PDF_maker(APIView):
    permission_classes = [AllowAny]
    def get(self,request,format=None,*args, **kwargs):
        if not request.GET.get("id"):return Response({"status":400},400)
        obj=Invoice.objects.filter(id=request.GET.get('id'))
        if not obj:return Response({"status":404},404)
        obj=obj.first()
        yaml_obj=Yaml.objects.filter(user=request.user)
        if not yaml_obj:
            return Response({"message":"configuration not found"},404)
        data = YamalReader(yaml_obj.first().yaml_file.file)
        ser_obj=InvoiceSerializerForPDF(obj)
        ser_obj.Meta.depth=1
        logger.error(ser_obj.data)
        fill_obj = FillValue(ser_obj.data, data)
        pdf_data = Submit(fill_obj.collect_all_data(),bill_image=str(yaml_obj.first().pdf_template.file)).draw_header_data()
        ser_obj.Meta.depth = 0
        pdf_file = io.BytesIO(pdf_data)
        pdf_file.seek(0)
        response = FileResponse(pdf_file, as_attachment=True, filename=f"{request.user.username}_{datetime.datetime.now().date()}_{obj.receiver.name}.pdf")
        return response