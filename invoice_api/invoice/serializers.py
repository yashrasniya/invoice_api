from rest_framework import serializers

from accounts.serializers.serializers import User_PublicSerializer
from .models import Invoice, Product, Product_properties, new_product_in_frontend, CustomField




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
            'formula',
            'on_with_out_gst_amount',
            'show_calculated_value',
            'presets',
            'default_value'
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
    receiver_gst_number = serializers.SerializerMethodField()
    vendor_name = serializers.SerializerMethodField()
    vendor_gst_number = serializers.SerializerMethodField()
    products = ProductSerializer(many=True,required=False)

    class Meta:
        model = Invoice
        fields = (
            'id',
            'user',
            'invoice_number',
            'receiver',
            'receiver_name',
            'receiver_gst_number',
            'vendor',
            'vendor_name',
            'vendor_gst_number',
            'date',
            'products',
            'gst_final_amount',
            'total_final_amount',
            'invoice_type',
            'payment_status',
            'payment_method',
            'custom_header_field'
        )
        read_only_fields =[
            'products']
    def get_user(self, obj):
        return obj.user.username

    def get_receiver_name(self,obj):
        if obj.receiver:
            return obj.receiver.name
        return ''

    def get_receiver_gst_number(self,obj):
        if obj.receiver:
            return obj.receiver.gst_number
        return ''

    def get_vendor_name(self, obj):
        if obj.vendor:
            return obj.vendor.name
        return ''

    def get_vendor_gst_number(self, obj):
        if obj.vendor:
            return obj.vendor.gst_number
        return ''

    def validate_custom_header_field(self, value):
        import json
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except Exception:
                pass

        if not isinstance(value, dict):
            return value
            
        cleaned_value = {}
        from invoice.models import CustomField
        
        request = self.context.get('request')
        user = request.user if request else None
        
        if user:
            active_fields = CustomField.objects.filter(user=user)
            if hasattr(user, 'user_company') and user.user_company:
                active_fields = active_fields | CustomField.objects.filter(company=user.user_company)
            casing_map = {cf.name.lower(): cf.name for cf in active_fields}
        else:
            casing_map = {}

        for k, v in value.items():
            normalized_key = casing_map.get(k.lower(), k)
            cleaned_value[normalized_key] = v
            
        return cleaned_value




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
            'vendor',
            'date',
            'products',
            'gst_final_amount',
            'total_final_amount',
            'invoice_type',
            'custom_header_field'
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
    receiver_gst_number = serializers.SerializerMethodField()
    vendor = serializers.SerializerMethodField()
    vendor_gst_number = serializers.SerializerMethodField()
    products_count = serializers.SerializerMethodField()
    taxable_amount = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = (
            'invoice_number',
            'receiver',
            'receiver_gst_number',
            'vendor',
            'vendor_gst_number',
            'date',
            'taxable_amount',
            'gst_final_amount',
            'total_final_amount',
            'payment_status',
            'payment_method',
            'products_count',
            'invoice_type'
        )
        read_only_fields =['gst_final_amount',
            'total_final_amount','products']

    def get_receiver(self,obj):
        if obj.receiver:
            return obj.receiver.name
        return ''
        
    def get_receiver_gst_number(self,obj):
        if obj.receiver:
            return obj.receiver.gst_number
        return ''
        
    def get_vendor(self, obj):
        if obj.vendor:
            return obj.vendor.name
        return ''

    def get_vendor_gst_number(self, obj):
        if obj.vendor:
            return obj.vendor.gst_number
        return ''
        
    def get_date(self, obj):
        if obj.date:
            return obj.date.strftime('%d/%m/%Y')
        return ''

    def get_products_count(self,obj):
        if obj.products:
            return obj.products.all().count()
        return 0

    def get_taxable_amount(self, obj):
        try:
            return float(obj.total_final_amount or 0) - float(obj.gst_final_amount or 0)
        except:
            return 0


class CustomFieldSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(source='company.company_name', read_only=True)
    
    class Meta:
        model = CustomField
        fields = [
            'id',
            'name',
            'field_type',
            'hidden',
            'default_value',
            'multioption_value',
            'company',
            'company_name',
            'created_time',
            'updated_time',
        ]
        read_only_fields = ['id', 'created_time', 'updated_time']