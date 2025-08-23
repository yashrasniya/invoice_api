from rest_framework import serializers

from bill_share.models import BillShare


class BillShareSerializers(serializers.ModelSerializer):

    class Meta:
        model = BillShare
        fields = '__all__'
