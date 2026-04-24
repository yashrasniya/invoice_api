import logging

import yaml
from django.conf import settings
from django.core.files.base import ContentFile
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
import os

from yaml_manager.api.serializer import Yaml_serializers
from yaml_manager.models import Yaml, YamlVersion
from yaml_reader import YamalReader, FillValue
import uuid
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)
# Create your views here.

class YamlView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self,request):
        if self.request.user.is_staff:
            yaml_obj = Yaml.objects.filter()

        else:
            yaml_obj=Yaml.objects.filter(company=request.user.user_company.id)
        if request.query_params.get("id"):
            yaml_obj = yaml_obj.filter(id=request.query_params.get("id"))
        if not yaml_obj:
            return Response({"message":"not found"},status=status.HTTP_404_NOT_FOUND)
            
        version_id = request.query_params.get("version_id")
        template = None
        if version_id:
            version_obj = yaml_obj.first().versions.filter(id=version_id).first()
            if version_obj:
                try:
                    yaml_data = yaml.safe_load(version_obj.version_data)
                    template = YamalReader(yaml_raw_data=yaml_data)
                except yaml.YAMLError:
                    pass
                    
        if not template:
            template = YamalReader(yaml_obj.first().yaml_file.file)

        if self.request.user.is_staff:
            user_company_obj = yaml_obj.first().company
        else:
            user_company_obj = request.user.user_company
        print(yaml_obj)
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
        t_name = yaml_obj.first().template_name
        if t_name == "Untitled Template" and user_company_obj and user_company_obj.company_name:
            t_name = user_company_obj.company_name
            
        template.yaml_raw_data['template_name'] = t_name
        template.yaml_raw_data['auto_save'] = yaml_obj.first().auto_save
        template.yaml_raw_data['pdf_template'] = request.build_absolute_uri(settings.MEDIA_URL + str(yaml_obj.first().pdf_template))
        
        versions = []
        for v in yaml_obj.first().versions.all():
            versions.append({
                "id": v.id,
                "created_at": v.created_at.strftime("%Y-%m-%d %H:%M:%S")
            })
        template.yaml_raw_data['versions_list'] = versions
        
        return Response(template.yaml_raw_data)

    def put(self,request):
        if self.request.user.is_staff:
            yaml_obj = Yaml.objects.filter()

        else:
            yaml_obj = Yaml.objects.filter(company=request.user.user_company.id)
        yaml_id = request.data.pop("id", None)
        request.data.pop("pdf_template", None)
        template_name = request.data.pop("template_name", None)
        auto_save = request.data.pop("auto_save", None)
        request.data.pop("versions_list", None)

        if not yaml_id:
             return Response({"error":"Missing ID"},400)

        yaml_obj= yaml_obj.filter(id=yaml_id)
        if not yaml_obj:
            return Response({"error":"Not Found"},404)

        yaml_str = yaml.dump(request.data, sort_keys=False)

        obj = yaml_obj.first()
        
        YamlVersion.objects.create(yaml=obj, version_data=yaml_str)
        try:
            limit = int(os.getenv('TEMPLATE_VERSION_LIMIT', 50))
        except ValueError:
            limit = 50
            
        versions = obj.versions.all()
        if versions.count() > limit:
            versions_to_delete = versions[limit:].values_list('id', flat=True)
            YamlVersion.objects.filter(id__in=list(versions_to_delete)).delete()
        
        if template_name:
            obj.template_name = template_name
        if auto_save is not None:
            obj.auto_save = auto_save
        obj.save()
            
        if obj.yaml_file and hasattr(obj.yaml_file, 'path'):
            with open(obj.yaml_file.path, 'w') as f:
                f.write(yaml_str)
        else:
            # Fallback if file doesn't exist yet for some reason
            obj.yaml_file.save(obj.yaml_file.name.split('/')[-1], ContentFile(yaml_str), save=True)

        versions = []
        for v in obj.versions.all():
            versions.append({
                "id": v.id,
                "created_at": v.created_at.strftime("%Y-%m-%d %H:%M:%S")
            })

        return Response({"message": "done", "versions_list": versions}, 200)

class YamlListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = Yaml_serializers

    def get_queryset(self):
        if self.request.user.is_staff and not self.request.GET.get('only_my'):
            return Yaml.objects.filter()
        return Yaml.objects.filter(company=self.request.user.user_company.id)

class ImageUploadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if 'image' not in request.FILES:
            return Response({"error": "No image provided"}, status=400)
        
        image_file = request.FILES['image']
        ext = image_file.name.split('.')[-1]
        filename = f"template_images/{uuid.uuid4()}.{ext}"
        
        path = default_storage.save(filename, ContentFile(image_file.read()))
        url = request.build_absolute_uri(settings.MEDIA_URL + path)
        
        return Response({"url": url}, status=200)
