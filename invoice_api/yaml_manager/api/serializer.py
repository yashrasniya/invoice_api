from rest_framework.serializers import ModelSerializer,SerializerMethodField

from yaml_manager.models import Yaml


class Yaml_serializers(ModelSerializer):
    user = SerializerMethodField()
    company = SerializerMethodField()
    template_name = SerializerMethodField()
    
    class Meta:
        model = Yaml
        fields = [
            'id',
            'template_name',
            'user',
            'company'
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