from django.contrib import admin
from .models import Category, Supplier, Product, StockMovement

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'description')
    search_fields = ('name',)

@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ('name', 'contact_person', 'email', 'phone', 'created_at')
    search_fields = ('name', 'contact_person', 'email')
    list_filter = ('created_at',)

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'category', 'supplier', 'price', 'gst_percentage', 'current_stock', 'reorder_level')
    search_fields = ('name', 'sku', 'description')
    list_filter = ('category', 'supplier', 'created_at')
    list_editable = ('price', 'gst_percentage', 'current_stock', 'reorder_level')
    autocomplete_fields = ['category', 'supplier']

@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ('product', 'movement_type', 'quantity', 'date')
    search_fields = ('product__name', 'product__sku', 'notes')
    list_filter = ('movement_type', 'date')
    autocomplete_fields = ['product']
    readonly_fields = ('date',)
