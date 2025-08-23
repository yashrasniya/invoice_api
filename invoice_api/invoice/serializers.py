from rest_framework import serializers

from accounts.serializers.serializers import User_PublicSerializer
from .models import Invoice, Product, Product_properties, new_product_in_frontend


def get_user(obj):
    return User_PublicSerializer(obj.user).data


class new_product_in_frontendSerializer(serializers.ModelSerializer):
    user=serializers.SerializerMethodField()
    class Meta:
        model = new_product_in_frontend
        fields = (
            'id',
            'user',
            'input_title',
            'size',
            'is_show',
            'is_calculable',
            'formula'
        )
    def get_user(self, obj):
        return obj.user.username


class Product_propertiesSerializer(serializers.ModelSerializer):
    new_product_in_frontend=serializers.SerializerMethodField()
    class Meta:
        model = Product_properties
        fields = (
            'id',
            'new_product_in_frontend',
            'value'
        )
    def get_new_product_in_frontend(self, obj):
        return new_product_in_frontendSerializer(obj.new_product_in_frontend).data

class ProductSerializer(serializers.ModelSerializer):
    product_properties=Product_propertiesSerializer(many=True,read_only=True)
    class Meta:
        model = Product
        fields = (
            'id',
            'product_properties',
            'gst_amount',
            'total_amount',
        )





class InvoiceSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    receiver_name = serializers.SerializerMethodField()
    products = ProductSerializer(many=True,required=False)

    class Meta:
        model = Invoice
        fields = (
            'id',
            'user',
            'invoice_number',
            'receiver',
            'receiver_name',
            'date',
            'products',
            'gst_final_amount',
            'total_final_amount'
        )
        read_only_fields =[
            'products']
    def get_user(self, obj):
        return obj.user.username

    def get_receiver_name(self,obj):
        if obj.receiver:
            return obj.receiver.name
        return ''



class InvoiceSerializerForPDF(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    date = serializers.SerializerMethodField()
    products = ProductSerializer(many=True,required=False)

    class Meta:
        model = Invoice
        fields = (
            'id',
            'user',
            'invoice_number',
            'receiver',
            'date',
            'products',
            'gst_final_amount',
            'total_final_amount'
        )
        read_only_fields =['gst_final_amount',
            'total_final_amount','products']
    def get_user(self, obj):
        return obj.user.username

    def get_date(self, obj):
        if obj.date:
            return obj.date.strftime('%d/%m/%Y')
        return ''


class InvoiceSerializerForCSV(serializers.ModelSerializer):
    date = serializers.SerializerMethodField()
    receiver = serializers.SerializerMethodField()
    products_count = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = (
            'invoice_number',
            'receiver',
            'date',
            'gst_final_amount',
            'total_final_amount',
            'products_count',
        )
        read_only_fields =['gst_final_amount',
            'total_final_amount','products']

    def get_receiver(self,obj):
        if obj.receiver:
            return obj.receiver.name
        return ''
    def get_date(self, obj):
        if obj.date:
            return obj.date.strftime('%d/%m/%Y')
        return ''

    def get_products_count(self,obj):
        if obj.products:
            return obj.products.all().count()
        return 0