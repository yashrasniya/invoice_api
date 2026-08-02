from rest_framework import viewsets, filters
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from invoice_api.permissions import HasFeature, HasPermission

from inventory.models import Category, Supplier, Product, StockMovement
from .serializers import CategorySerializer, SupplierSerializer, ProductSerializer, StockMovementSerializer

# subscription gate: plan must include the inventory feature
InventoryFeature = HasFeature.with_code('inventory')
InventoryManage = HasPermission.with_code('inventory.manage')


class CompanyScopedViewSet(viewsets.ModelViewSet):
    """Every read/write is limited to the requester's company; new rows are
    stamped with it automatically."""
    permission_classes = [IsAuthenticated, InventoryFeature, InventoryManage]

    def _company(self):
        return getattr(self.request, 'company', None) or self.request.user.user_company

    def get_queryset(self):
        return self.queryset.filter(company=self._company())

    def perform_create(self, serializer):
        serializer.save(company=self._company())


class CategoryViewSet(CompanyScopedViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'description']


class SupplierViewSet(CompanyScopedViewSet):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'contact_person', 'email', 'phone']


class ProductViewSet(CompanyScopedViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['category', 'supplier', 'vendor']
    search_fields = ['name', 'sku', 'description']


class StockMovementViewSet(viewsets.ModelViewSet):
    """Scoped through the product's company."""
    permission_classes = [IsAuthenticated, InventoryFeature, InventoryManage]
    queryset = StockMovement.objects.all()
    serializer_class = StockMovementSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['product', 'movement_type']
    search_fields = ['product__name', 'product__sku', 'notes']

    def _company(self):
        return getattr(self.request, 'company', None) or self.request.user.user_company

    def get_queryset(self):
        return self.queryset.filter(product__company=self._company())

    def perform_create(self, serializer):
        product = serializer.validated_data.get('product')
        if product is None or product.company_id != getattr(self._company(), 'id', None):
            raise ValidationError({'product': 'Product not found in your company.'})
        serializer.save()
