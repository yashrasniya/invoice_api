from rest_framework import serializers
from .models import Customers, Vendor


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


class CustomerStatsSerializer(CompanySerializer):
    """Customer row plus its billing history in numbers.

    The three extra fields are queryset annotations, not model fields, so
    this serializer only works on a queryset run through
    `companies.api.views.annotate_customer_stats`. It is served only to
    plans carrying `advanced_reports`.
    """
    invoice_count = serializers.IntegerField(read_only=True)
    total_billed = serializers.DecimalField(
        max_digits=20, decimal_places=2, read_only=True)
    last_invoice_date = serializers.DateField(read_only=True)

    class Meta(CompanySerializer.Meta):
        fields = CompanySerializer.Meta.fields + (
            'invoice_count',
            'total_billed',
            'last_invoice_date',
        )


class VendorSerializer(serializers.ModelSerializer):
    user=serializers.SerializerMethodField()
    class Meta:
        model = Vendor
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
