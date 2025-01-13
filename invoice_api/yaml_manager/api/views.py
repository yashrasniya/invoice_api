from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from yaml_manager.models import Yaml
from yaml_reader import YamalReader


# Create your views here.

class YamlView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self,request):
        yaml_obj=Yaml.objects.filter(user=request.user)
        if not yaml_obj:
            return Response({"message":"not found"},status=status.HTTP_404_NOT_FOUND)

        return Response(YamalReader(yaml_obj.first().yaml_file.file).yaml_raw_data)
