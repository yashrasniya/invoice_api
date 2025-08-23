from rest_framework.serializers import ModelSerializer

from yaml_manager.models import Yaml


class Yaml_serializers(ModelSerializer):

    class Meta:
        model = Yaml
        fields = [
            'id',
            'template_name',
        ]