from rest_framework import serializers
from .models import Companies


class CompanySerializer(serializers.ModelSerializer):
    user=serializers.SerializerMethodField()
    class Meta:
        model = Companies
        fields = (
            'id',
            'name',
            'user',
            'address',
            'gst_number',
            'state',
            'state_code'
        )
        extra_kwargs = {"name": {"required": True, "allow_null": False}}
    def get_user(self, obj):
        return obj.user.username
