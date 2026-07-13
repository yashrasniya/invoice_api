from rest_framework import serializers
from inventory.models import Category, Supplier, Product, StockMovement

def _request_company(serializer):
    request = serializer.context.get('request')
    if request is None:
        return None
    return getattr(request, 'company', None) or request.user.user_company


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = '__all__'
        read_only_fields = ('company',)  # stamped from the request

    def validate_name(self, value):
        qs = Category.objects.filter(company=_request_company(self), name=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('A category with this name already exists.')
        return value

class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = '__all__'
        read_only_fields = ('company',)

class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.ReadOnlyField(source='category.name')
    supplier_name = serializers.ReadOnlyField(source='supplier.name')
    vendor_name = serializers.ReadOnlyField(source='vendor.name')

    def validate_vendor(self, value):
        # vendor must belong to the requester's company (vendors are keyed
        # to their creating user)
        if value is not None:
            company = _request_company(self)
            if value.user.user_company_id != getattr(company, 'id', None):
                raise serializers.ValidationError('Vendor not found in your company.')
        return value

    class Meta:
        model = Product
        fields = '__all__'
        read_only_fields = ('company',)

    def validate_sku(self, value):
        qs = Product.objects.filter(company=_request_company(self), sku=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('A product with this SKU already exists.')
        return value

class StockMovementSerializer(serializers.ModelSerializer):
    product_name = serializers.ReadOnlyField(source='product.name')

    class Meta:
        model = StockMovement
        fields = '__all__'
        read_only_fields = ('product_name',)

    def validate_quantity(self, value):
        if value is None or value <= 0:
            raise serializers.ValidationError('Quantity must be a positive number.')
        return value
