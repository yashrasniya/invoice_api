from rest_framework import serializers

from upi_qr import is_valid_upi_id
from ..models import UserCompanies

class UserCompaniesSerializer(serializers.ModelSerializer):
    subscriptions_plan = serializers.IntegerField(read_only=True)
    company_logo = serializers.FileField(required=False,)
    class Meta:
        model = UserCompanies
        fields = "__all__"

    def validate_upi_id(self, value):
        # A typo'd VPA produces a QR that fails only inside the payer's bank
        # app, long after the invoice has gone out — reject it at save time.
        if not value:
            return value
        value = value.strip()
        if not is_valid_upi_id(value):
            raise serializers.ValidationError(
                "Enter a valid UPI id in the form name@bank, e.g. acme@okaxis.")
        return value

    def validate(self, attrs):
        upi_id = attrs.get('upi_id', getattr(self.instance, 'upi_id', None))
        if attrs.get('show_upi_qr') and not upi_id:
            raise serializers.ValidationError(
                {'upi_id': "Add a UPI id before enabling the invoice QR code."})
        return attrs
