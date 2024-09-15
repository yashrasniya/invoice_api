from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from companies.models import Companies
from ..serializers import CompanySerializer


class CompaniesView(ListAPIView):
    serializer_class = CompanySerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Companies.objects.filter(user=self.request.user)

    def post(self,request,*args,**kwargs):
        print(request.POST)
        serializer = CompanySerializer(data=request.data)
        if serializer.is_valid():
            print(serializer.validated_data)
            serializer.save(user=self.request.user)
            return Response(serializer.data)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)