from rest_framework import serializers
from .models import Companies


class CompanySerializer(serializers.ModelSerializer):
    class Meta:
        model = Companies
        fields = (
            'name',
            'user',
            'address',
            'gst_number',
            'state',
            'state_code'
        )
