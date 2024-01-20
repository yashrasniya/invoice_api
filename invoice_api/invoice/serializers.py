from rest_framework import serializers

from accounts.serializers import User_PublicSerializer
from .models import Invoice, Product, Product_properties, new_product_in_frontend


def get_user(obj):
    return User_PublicSerializer(obj.user).data


class InvoiceSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = (
            'user',
            'invoice_number',
            'receiver',
            'date',
            'products',
            'gst_final_amount',
            'total_final_amount'
        )


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = (
            'product_properties',
            'gst_amount',
            'total_amount',
            'new_product_in_frontend',
            'value'
        )


class Product_propertiesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product_properties
        fields = (
            'new_product_in_frontend',
            'value'
        )


class new_product_in_frontendSerializer(serializers):
    class Meta:
        model = new_product_in_frontend
        fields = (
            'user',
            'input_title',
            'size',
            'is_show',
            'is_calculable',
            'formula'
        )
