from rest_framework.serializers import ModelSerializer,SerializerMethodField

from yaml_manager.models import Yaml


class Yaml_serializers(ModelSerializer):
    user = SerializerMethodField()
    company = SerializerMethodField()
    template_name = SerializerMethodField()
    pdf_template = SerializerMethodField()
    
    class Meta:
        model = Yaml
        fields = [
            'id',
            'template_name',
            'pdf_template',
            'user',
            'company',
            'is_html',
            'is_default',
            'is_global',
            'global_category',
            'is_published',
        ]

    def get_template_name(self, obj):
        if obj.template_name == "Untitled Template" and obj.company and obj.company.company_name:
            return obj.company.company_name
        return obj.template_name

    def get_user(self,obj):
        if obj.user:
            return obj.user.username
        return  '-'

    def get_company(self,obj):
        if obj.company:
            return obj.company.company_name
        return  '-'

    def get_pdf_template(self, obj):
        if obj.pdf_template:
            request = self.context.get('request')
            if request:
                from django.conf import settings
                return request.build_absolute_uri(settings.MEDIA_URL + str(obj.pdf_template))
        return None


class GlobalTemplateSerializer(ModelSerializer):
    user = SerializerMethodField()
    pdf_template = SerializerMethodField()

    class Meta:
        model = Yaml
        fields = [
            'id',
            'template_name',
            'pdf_template',
            'global_category',
            'is_html',
            'user',
            'is_published',
            'description',
            'page_size',
            'version',
        ]

    def get_user(self, obj):
        if obj.user:
            return obj.user.username
        return '-'

    def get_pdf_template(self, obj):
        if obj.pdf_template:
            request = self.context.get('request')
            if request:
                from django.conf import settings
                return request.build_absolute_uri(settings.MEDIA_URL + str(obj.pdf_template))
        return None