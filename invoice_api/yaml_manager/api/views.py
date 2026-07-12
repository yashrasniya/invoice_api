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

from invoice_api.permissions import HasMethodFeature, HasMethodPermission

from yaml_manager.api.serializer import Yaml_serializers
from yaml_manager.models import Yaml, YamlVersion
from yaml_reader import YamalReader, FillValue
import uuid
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)
# Create your views here.

class YamlView(APIView):
    # reads stay open (PDF rendering needs templates); designing requires the
    # plan feature AND the template.manage permission (tenant-admin granted)
    permission_classes = [IsAuthenticated, HasMethodFeature, HasMethodPermission]
    required_features_map = {'POST': 'template_designer',
                             'PUT': 'template_designer',
                             'DELETE': 'template_designer'}
    required_permissions_map = {'POST': 'template.manage',
                                'PUT': 'template.manage',
                                'DELETE': 'template.manage'}

    def get(self,request):
        if self.request.user.is_staff:
            yaml_obj = Yaml.objects.filter()

        else:
            yaml_obj=Yaml.objects.filter(company=request.user.user_company.id)
        if request.query_params.get("id"):
            yaml_obj = yaml_obj.filter(id=request.query_params.get("id"))
        if request.query_params.get("is_html"):
            is_html_param = request.query_params.get("is_html").lower() == 'true'
            yaml_obj = yaml_obj.filter(is_html=is_html_param)
            
        if not yaml_obj:
            return Response({"message":"not found"},status=status.HTTP_404_NOT_FOUND)
            
        first_obj = yaml_obj.first()
        if first_obj.is_html:
            html_content = ""
            try:
                version_id = request.query_params.get("version_id")
                if version_id:
                    version_obj = first_obj.versions.filter(id=version_id).first()
                    if version_obj:
                        html_content = version_obj.version_data
                if not html_content and first_obj.yaml_file:
                    first_obj.yaml_file.file.seek(0)
                    html_content = first_obj.yaml_file.file.read().decode('utf-8')
            except Exception as e:
                logger.error(f"Error reading HTML file in GET: {e}")
                
            versions = []
            for v in first_obj.versions.all():
                versions.append({
                    "id": v.id,
                    "created_at": v.created_at.strftime("%Y-%m-%d %H:%M:%S")
                })

            data = {
                'id': first_obj.id,
                'template_name': first_obj.template_name,
                'is_html': True,
                'auto_save': first_obj.auto_save,
                'pdf_template': request.build_absolute_uri(settings.MEDIA_URL + str(first_obj.pdf_template)) if first_obj.pdf_template else None,
                'versions_list': versions,
                'elements': first_obj.elements if (first_obj.elements and len(first_obj.elements) > 0) else [
                    {
                        'id': '1',
                        'type': 'html',
                        'content': html_content,
                        'x': 0, 'y': 0, 'width': 595, 'height': 842
                    }
                ]
            }
            return Response(data)

        # Non-HTML / YAML workflow
        version_id = request.query_params.get("version_id")
        template = None
        if version_id:
            version_obj = first_obj.versions.filter(id=version_id).first()
            if version_obj:
                try:
                    yaml_data = yaml.safe_load(version_obj.version_data)
                    template = YamalReader(yaml_raw_data=yaml_data)
                except yaml.YAMLError:
                    pass
                    
        if not template:
            template = YamalReader(first_obj.yaml_file.file)

        if self.request.user.is_staff:
            user_company_obj = first_obj.company
        else:
            user_company_obj = request.user.user_company

        for key in template.yaml_raw_data.get("Bill", {}):
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

        is_html = yaml_obj.first().is_html
        obj = yaml_obj.first()
        
        if is_html:
            file_content = request.data.get("html_content", "")
            ext = ".html"
            elements = request.data.get("elements", None)
            if elements is not None:
                obj.elements = elements
        else:
            file_content = yaml.dump(request.data, sort_keys=False)
            ext = ".yaml"
            
        YamlVersion.objects.create(yaml=obj, version_data=file_content)
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
                f.write(file_content)
        else:
            # Fallback if file doesn't exist yet for some reason
            obj.yaml_file.save(f"{uuid.uuid4()}{ext}", ContentFile(file_content), save=True)

        versions = []
        for v in obj.versions.all():
            versions.append({
                "id": v.id,
                "created_at": v.created_at.strftime("%Y-%m-%d %H:%M:%S")
            })

        return Response({"message": "done", "versions_list": versions, "id": obj.id}, 200)

    def post(self, request):
        template_name = request.data.get("template_name", "Untitled Template")
        is_html = request.data.get("is_html", False)
        elements = request.data.get("elements", None)
        
        company = request.user.user_company if not self.request.user.is_staff else None
        
        obj = Yaml.objects.create(
            user=request.user,
            company=company,
            template_name=template_name,
            is_html=is_html,
            elements=elements
        )
        
        if is_html:
            file_content = request.data.get("html_content", "")
            file_name = f"{uuid.uuid4()}.html"
        else:
            file_content = yaml.dump(request.data, sort_keys=False)
            file_name = f"{uuid.uuid4()}.yaml"
        print(file_name)
        obj.yaml_file.save(file_name, ContentFile(file_content), save=True)
        YamlVersion.objects.create(yaml=obj, version_data=file_content)
        
        return Response({"id": obj.id, "message": "created successfully"}, status=201)

class YamlListView(ListAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = Yaml_serializers

    def get_queryset(self):
        if self.request.user.is_staff and not self.request.GET.get('only_my'):
            return Yaml.objects.filter()
        return Yaml.objects.filter(company=self.request.user.user_company.id)

class YamlSetDefaultView(APIView):
    """Mark a company template as the default for PDF export.
    POST /api/yaml/<id>/set-default/  (permission: template.manage;
    no plan feature needed — it's configuration, not designing)."""
    permission_classes = [IsAuthenticated, HasMethodPermission]
    required_permissions_map = {'POST': 'template.manage'}

    def post(self, request, id):
        company = request.user.user_company
        template = Yaml.objects.filter(id=id, company=company).first()
        if template is None:
            return Response({'error': 'Template not found in your company.'},
                            status=status.HTTP_400_BAD_REQUEST)
        Yaml.objects.filter(company=company, is_default=True).update(is_default=False)
        template.is_default = True
        template.save(update_fields=['is_default'])
        return Response({'id': template.id, 'is_default': True})


class ImageUploadView(APIView):
    permission_classes = [IsAuthenticated, HasMethodFeature, HasMethodPermission]
    required_features_map = {'POST': 'template_designer'}
    required_permissions_map = {'POST': 'template.manage'}

    def post(self, request):
        if 'image' not in request.FILES:
            return Response({"error": "No image provided"}, status=400)
        
        image_file = request.FILES['image']
        ext = image_file.name.split('.')[-1]
        filename = f"template_images/{uuid.uuid4()}.{ext}"
        
        path = default_storage.save(filename, ContentFile(image_file.read()))
        url = request.build_absolute_uri(settings.MEDIA_URL + path)
        
        return Response({"url": url}, status=200)

class WeasyprintPreviewView(APIView):
    permission_classes = [IsAuthenticated, HasMethodFeature, HasMethodPermission]
    required_features_map = {'POST': 'template_designer'}
    required_permissions_map = {'POST': 'template.manage'}

    def post(self, request):
        html_content = request.data.get("html_content")
        if not html_content:
            return Response({"error": "html_content is required"}, status=400)
            
        import weasyprint
        import io
        import datetime
        from django.http import FileResponse
        from django.template import Template, Context

        # Prepare rich dummy data context for template rendering
        today_str = datetime.datetime.now().strftime('%Y-%m-%d')
        due_date_str = (datetime.datetime.now() + datetime.timedelta(days=30)).strftime('%Y-%m-%d')
        
        company_name = "Acme Corporation"
        company_logo_url = "https://via.placeholder.com/150"
        if request.user and hasattr(request.user, 'user_company') and request.user.user_company:
            if request.user.user_company.company_name:
                company_name = request.user.user_company.company_name
            if request.user.user_company.company_logo:
                company_logo_url = request.build_absolute_uri(request.user.user_company.company_logo.url)
        print(company_logo_url)
        company_data = {
            'company_name': company_name,
            'company_logo': company_logo_url,
            'company_address': "123 Business Lane, Suite 100, Financial District",
            'company_phone': "+1 (555) 019-2834",
            'company_email': "billing@acme.com",
            'gst_number': "22AAAAA0000A1Z5",
        }
        
        dummy_products = [
            {
                'props': {
                    'item': 'Web Development Services',
                    'description': 'Frontend UI Design & API Integration',
                    'quantity': '1',
                    'rate': '800.00',
                    'amount': '800.00',
                },
                'total_amount': '800.00'
            },
            {
                'props': {
                    'item': 'Cloud Hosting Setup',
                    'description': 'AWS Deployment & Configuration',
                    'quantity': '2',
                    'rate': '100.00',
                    'amount': '200.00',
                },
                'total_amount': '200.00'
            }
        ]
        
        invoice_data = {
            'invoice_number': "INV-2026-0001",
            'date': today_str,
            'due_date': due_date_str,
            'receiver_name': "Acme Client Enterprises",
            'receiver_address': "456 Client Boulevard, Innovation Hub",
            'receiver_phone': "+1 (555) 014-9988",
            'receiver_email': "accounts@acmeclient.com",
            'total_final_amount': 1180.00,
            'gst_final_amount': 180.00,
            'products': dummy_products,
        }
        
        footer_data = {
            'total_amount_with_out_gst': 1000.00,
            'gst_amount': 180.00,
            'total_amount_with_gst': 1180.00,
            'total_amount_in_text': "One Thousand One Hundred Eighty Rupees Only",
            'center_gst_amount': 90.00,
            'state_gst_amount': 90.00,
            'gst': 18.00,
            'center_gst': 9.00,
            'state_gst': 9.00
        }
        
        context_dict = {
            'invoice': invoice_data,
            'company': company_data,
            'footer': footer_data,
            'products_data': [p['props'] for p in dummy_products]
        }

        try:
            django_template = Template(html_content)
            html_content = django_template.render(Context(context_dict))
        except Exception as e:
            logger.error(f"Error rendering preview template: {e}")

        try:
            pdf_file = weasyprint.HTML(string=html_content).write_pdf()
            buffer = io.BytesIO(pdf_file)
            buffer.seek(0)
            return FileResponse(buffer, as_attachment=False, filename='preview.pdf', content_type='application/pdf')
        except Exception as e:
            return Response({"error": str(e)}, status=500)
