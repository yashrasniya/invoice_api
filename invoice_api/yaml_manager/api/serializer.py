from rest_framework.serializers import ModelSerializer,SerializerMethodField

from yaml_manager.models import Yaml


class Yaml_serializers(ModelSerializer):
    user = SerializerMethodField()
    company = SerializerMethodField()
    class Meta:
        model = Yaml
        fields = [
            'id',
            'template_name',
            'user',
            'company'

        ]

    def get_user(self,obj):
        if obj.user:
            return obj.user.username
        return  '-'

    def get_company(self,obj):
        if obj.company:
            return obj.company.company_name
        return  '-'