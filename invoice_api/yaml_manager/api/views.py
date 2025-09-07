import logging

import yaml
from django.conf import settings
from django.core.files.base import ContentFile
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from yaml_manager.api.serializer import Yaml_serializers
from yaml_manager.models import Yaml
from yaml_reader import YamalReader, FillValue

logger = logging.getLogger(__name__)
# Create your views here.

class YamlView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self,request):
        yaml_obj=Yaml.objects.filter(company=request.user.user_company.id)
        if request.query_params.get("id"):
            yaml_obj = yaml_obj.filter(id=request.query_params.get("id"))
        if not yaml_obj:
            return Response({"message":"not found"},status=status.HTTP_404_NOT_FOUND)
        template = YamalReader(yaml_obj.first().yaml_file.file)
        user_company_obj = request.user.user_company
        for key in template.yaml_raw_data.get("Bill"):
            if key != "product":
                objs = template.yaml_raw_data.get("Bill")[key]
            else:
                objs = template.yaml_raw_data.get("Bill")[key]["product_list"]
            for obj in objs:
                if isinstance(obj,dict) and obj.keys():
                    obj_key = list(obj.keys())[0]
                    name = str(str(obj[obj_key].get("label",'')).lower())
                    if hasattr(user_company_obj,name):
                        if obj[obj_key].get("rectangles_type"):
                            try:
                                height = user_company_obj.logo_scaled_height(obj[obj_key].get("width"))
                                src_obj = getattr(user_company_obj, name)
                                src_url = request.build_absolute_uri(settings.MEDIA_URL + str(src_obj))
                                print(src_url)
                                obj[obj_key]["src"] = src_url
                                obj[obj_key]["height"] = height
                            except Exception as e:
                                logger.error(e)

                        else:
                            obj[obj_key]["value"] = str(getattr(user_company_obj,name))
        template.yaml_raw_data['id'] = yaml_obj.first().id
        template.yaml_raw_data['pdf_template'] = request.build_absolute_uri(settings.MEDIA_URL + str(yaml_obj.first().pdf_template))
        print(template.yaml_raw_data)
        return Response(template.yaml_raw_data)

    def put(self,request):
        yaml_obj = Yaml.objects.filter(company=request.user.user_company.id)
        yaml_id = request.data.pop("id")
        request.data.pop("pdf_template")
        yaml_obj= yaml_obj.filter(id=yaml_id)
        if not yaml_obj:
            return Response({"error":"Not Found"},404)

        yaml_str = yaml.dump(request.data, sort_keys=False)

        obj = yaml_obj.first()
        obj.yaml_file.save(obj.yaml_file.name.split('/')[-1], ContentFile(yaml_str), save=True)

        return Response("done",200)

class YamlListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = Yaml_serializers

    def get_queryset(self):
        if self.request.user.is_staff and not self.request.GET.get('only_my'):
            return Yaml.objects.filter()
        return Yaml.objects.filter(company=self.request.user.user_company.id)

