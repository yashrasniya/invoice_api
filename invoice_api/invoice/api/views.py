from datetime import datetime

from django.forms import renderers
from rest_framework import status, viewsets, pagination
from rest_framework.generics import ListAPIView, RetrieveUpdateAPIView
from rest_framework.permissions import IsAuthenticated,AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from invoice.models import Invoice, Product, new_product_in_frontend, Product_properties
from ..serializers import InvoiceSerializer, new_product_in_frontendSerializer, ProductSerializer, \
    Product_propertiesSerializer


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
        obj = Invoice.objects.filter(id=id)
        if not obj.exists():
            return Response({'message': 'id not found'}, status=status.HTTP_404_NOT_FOUND)
        serializer = InvoiceSerializer(obj.first(), data=request.data)

        if serializer.is_valid():
            serializer.save()
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

from io import BytesIO
from django.http import HttpResponse
from django.template.loader import get_template

from xhtml2pdf import pisa
def render_to_pdf(template_src, context_dict={}):
    template = get_template(template_src)
    html  = template.render(context_dict)
    result = BytesIO()
    pdf = pisa.pisaDocument(BytesIO(html.encode("ISO-8859-1")), result)
    if pdf.err:
        return HttpResponse("Invalid PDF", status_code=400, content_type='text/plain')
    return HttpResponse(result.getvalue(), content_type='application/pdf')
class PDF_maker(APIView):
    permission_classes = [AllowAny]
    def get(self,request,format=None,*args, **kwargs):
        data = {
            'today': datetime.today(),
            'amount': 39.99,
            'customer_name': 'Cooper Mann',
            'invoice_number': 1233434,
        }
        return render_to_pdf('invoice.html', data)