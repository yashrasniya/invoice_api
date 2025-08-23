from rest_framework import serializers
from ..models import UserCompanies

class UserCompaniesSerializer(serializers.ModelSerializer):
    subscriptions_plan = serializers.IntegerField(read_only=True)
    company_logo = serializers.FileField(required=False,)
    class Meta:
        model = UserCompanies
        fields = "__all__"

