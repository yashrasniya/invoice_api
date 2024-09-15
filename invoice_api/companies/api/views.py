from rest_framework import status, pagination, filters
from rest_framework.authentication import TokenAuthentication
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from companies.models import Companies
from ..serializers import CompanySerializer


class CompaniesView(ListAPIView):
    serializer_class = CompanySerializer
    permission_classes = [IsAuthenticated]
    pagination_class = pagination.PageNumberPagination
    filter_backends = [filters.SearchFilter]
    search_fields = ['name']


    def get_queryset(self):
        return Companies.objects.filter(user=self.request.user).order_by('-id')

    def post(self,request,*args,**kwargs):
        print(request.POST)
        if kwargs.get('id','') :
            if Companies.objects.filter(id=kwargs.get('id')):
                serializer = CompanySerializer( Companies.objects.get(id=kwargs.get('id')),data=request.data)
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

        if not Companies.objects.filter(id=self.kwargs.get('id')):
            return Response({'error': 'id not found'}, status=status.HTTP_400_BAD_REQUEST)
        Companies.objects.get(id=self.kwargs.get('id')).delete()
        return Response({"message":"delete successfully"},status=status.HTTP_204_NO_CONTENT)