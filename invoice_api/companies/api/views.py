from rest_framework import status, pagination, filters
from rest_framework.authentication import TokenAuthentication
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from invoice_api.permissions import HasMethodPermission
from invoice_api.scoping import user_scope_q

from companies.models import Customers, Vendor
from ..serializers import CompanySerializer, VendorSerializer

class MyPaginator( pagination.PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 1000

class CompaniesView(ListAPIView):
    serializer_class = CompanySerializer
    permission_classes = [IsAuthenticated, HasMethodPermission]
    required_permissions_map = {'POST': 'customer.manage',
                                'DELETE': 'customer.manage'}
    pagination_class = MyPaginator
    filter_backends = [filters.SearchFilter]
    search_fields = ['name']


    def get_queryset(self):
        return Customers.objects.filter(user_scope_q(self.request)).order_by('id')

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
    filter_backends = [filters.SearchFilter]
    search_fields = ['name']


    def get_queryset(self):
        return Vendor.objects.filter(user_scope_q(self.request)).order_by('id')

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