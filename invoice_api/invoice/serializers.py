from rest_framework import serializers

from accounts.serializers.serializers import User_PublicSerializer
from invoice_api.gst import STATE_NAMES, is_valid_state_code
from invoice_api.media_urls import absolute_media_url
from invoice_api.scoping import user_scope_q
from .models import Invoice, Product, Product_properties, new_product_in_frontend, CustomField, ProductImage




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

class ProductImageSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.SerializerMethodField()

    class Meta:
        model = ProductImage
        fields = (
            'id',
            'image',
            'original_filename',
            'uploaded_by',
            'created_at',
        )
        read_only_fields = ('id', 'original_filename', 'uploaded_by', 'created_at')

    def get_uploaded_by(self, obj):
        return obj.user.username if obj.user else None

    def to_representation(self, instance):
        # `image` is kept as a real ImageField (not a SerializerMethodField)
        # so uploads still validate/write normally; only the *read* URL is
        # rebuilt here, prefix-aware, in place of DRF's default absolute URI.
        ret = super().to_representation(instance)
        request = self.context.get('request')
        if request is not None and instance.image:
            ret['image'] = absolute_media_url(request, instance.image.url)
        return ret


class ProductSerializer(serializers.ModelSerializer):
    product_properties=Product_propertiesSerializer(many=True,read_only=True)
    image = ProductImageSerializer(read_only=True)
    # write-only handle for attaching/replacing the line item's image; scoped
    # to the requester's company below so a product can't be pointed at
    # another tenant's image library entry
    image_id = serializers.PrimaryKeyRelatedField(
        source='image', write_only=True, required=False, allow_null=True,
        queryset=ProductImage.objects.none())

    class Meta:
        model = Product
        fields = (
            'id',
            'product_properties',
            'gst_amount',
            'total_amount',
            'image',
            'image_id',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        request = self.context.get('request')
        if request is not None:
            company = getattr(request, 'company', None)
            enabled = ('line_item_images' in (getattr(request, 'features', None) or set())
                       and bool(company and getattr(company, 'enable_line_item_images', False)))
            if enabled:
                self.fields['image_id'].queryset = ProductImage.objects.filter(user_scope_q(request))
            # else: queryset stays ProductImage.objects.none() — any
            # submitted image_id fails validation instead of attaching,
            # since the company hasn't turned the feature on.





class InvoiceSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    receiver_name = serializers.SerializerMethodField()
    receiver_gst_number = serializers.SerializerMethodField()
    receiver_state = serializers.SerializerMethodField()
    receiver_state_code = serializers.SerializerMethodField()
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
            'receiver_state',
            'receiver_state_code',
            'vendor',
            'vendor_name',
            'vendor_gst_number',
            'date',
            'due_date',
            'place_of_supply',
            'customer_notes',
            'terms',
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

    def get_receiver_state(self, obj):
        if obj.receiver:
            return obj.receiver.state
        return ''

    def get_receiver_state_code(self, obj):
        if obj.receiver:
            return obj.receiver.state_code
        return None

    def validate_place_of_supply(self, value):
        # Same list the GST reports use; anything else is a data-entry error.
        if value is not None and not is_valid_state_code(value):
            raise serializers.ValidationError('Choose a valid GST state.')
        return value

    def validate(self, attrs):
        # Compare against the stored date on partial updates, since the client
        # may send only one of the two.
        date = attrs['date'] if 'date' in attrs else getattr(self.instance, 'date', None)
        due = attrs['due_date'] if 'due_date' in attrs else getattr(self.instance, 'due_date', None)
        if date and due and due < date:
            raise serializers.ValidationError(
                {'due_date': "Due date can't be before the invoice date."})
        return attrs

    def get_vendor_name(self, obj):
        if obj.vendor:
            return obj.vendor.name
        return ''

    def get_vendor_gst_number(self, obj):
        if obj.vendor:
            return obj.vendor.gst_number
        return ''

    def validate_invoice_number(self, value):
        # A cleared number stores as NULL, matching existing rows, rather than
        # introducing '' as a second empty representation.
        if value is not None and not str(value).strip():
            return None
        return value

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
    # Printable text for the template editors (YAML and HTML): a template label
    # such as `due_date` or `notes` is filled from these keys.
    due_date = serializers.SerializerMethodField()
    place_of_supply = serializers.SerializerMethodField()
    payment_status = serializers.SerializerMethodField()
    payment_method = serializers.SerializerMethodField()
    notes = serializers.SerializerMethodField()
    terms = serializers.SerializerMethodField()
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
            'due_date',
            'place_of_supply',
            'payment_status',
            'payment_method',
            'notes',
            'terms',
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

    def get_due_date(self, obj):
        # same format as `date`, so the two print alike on a template
        if obj.due_date:
            return obj.due_date.strftime('%d/%m/%Y')
        return ''

    def get_place_of_supply(self, obj):
        code = obj.place_of_supply
        if not code:
            return ''
        name = STATE_NAMES.get(code)
        return f'{name} ({code})' if name else str(code)

    def get_payment_status(self, obj):
        return obj.get_payment_status_display()

    def get_payment_method(self, obj):
        return obj.get_payment_method_display() if obj.payment_method else ''

    def get_notes(self, obj):
        return obj.customer_notes or ''

    def get_terms(self, obj):
        return obj.terms or ''


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