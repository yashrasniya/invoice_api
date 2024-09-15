from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from companies.models import Companies
from ..serializers import CompanySerializer

class CompaniesView(ListAPIView):
    serializer_class = CompanySerializer

    def get_queryset(self):
        return Companies.objcets.filter(user=self.request.user)


