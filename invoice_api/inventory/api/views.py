from rest_framework import viewsets, filters
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend

from invoice_api.permissions import HasFeature

from inventory.models import Category, Supplier, Product, StockMovement
from .serializers import CategorySerializer, SupplierSerializer, ProductSerializer, StockMovementSerializer

# subscription gate: plan must include the inventory feature
InventoryFeature = HasFeature.with_code('inventory')


class CategoryViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, InventoryFeature]
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'description']

class SupplierViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, InventoryFeature]
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'contact_person', 'email', 'phone']

class ProductViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, InventoryFeature]
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['category', 'supplier']
    search_fields = ['name', 'sku', 'description']

class StockMovementViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated, InventoryFeature]
    queryset = StockMovement.objects.all()
    serializer_class = StockMovementSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['product', 'movement_type']
    search_fields = ['product__name', 'product__sku', 'notes']
