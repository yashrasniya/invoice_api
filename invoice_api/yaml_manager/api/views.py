from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from yaml_manager.api.serializer import Yaml_serializers
from yaml_manager.models import Yaml
from yaml_reader import YamalReader


# Create your views here.

class YamlView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self,request):
        yaml_obj=Yaml.objects.filter(company=request.user.user_company.id)
        if request.query_params.get("id"):
            yaml_obj = yaml_obj.filter(id__in=request.query_params.get("id"))
        if not yaml_obj:
            return Response({"message":"not found"},status=status.HTTP_404_NOT_FOUND)

        return Response(YamalReader(yaml_obj.first().yaml_file.file).yaml_raw_data)

class YamlListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = Yaml_serializers

    def get_queryset(self):
        return Yaml.objects.filter(company=self.request.user.user_company.id)

