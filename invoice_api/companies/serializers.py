from rest_framework import serializers
from .models import Customers


class CompanySerializer(serializers.ModelSerializer):
    user=serializers.SerializerMethodField()
    class Meta:
        model = Customers
        fields = (
            'id',
            'name',
            'user',
            'address',
            'gst_number',
            'phone_number',
            'state',
            'state_code'
        )
        extra_kwargs = {
            "name": {"required": True, "allow_null": False},
            "phone_number": {"required": False, "allow_null": True}
                        }
    def get_user(self, obj):
        return obj.user.username
