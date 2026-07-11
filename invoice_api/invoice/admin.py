from django.contrib import admin
from .models import Invoice, Product, Product_properties, new_product_in_frontend, Font, InvoiceExtractionLog, CustomField


class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('id','user', 'invoice_number', 'receiver', 'date', 'gst_final_amount', 'total_final_amount')


class ProductAdmin(admin.ModelAdmin):
    list_display = ('id','gst_amount', 'total_amount')


class Product_propertiesAdmin(admin.ModelAdmin):
    list_display = ('new_product_in_frontend', 'value')


class new_product_in_frontendAdmin(admin.ModelAdmin):
    list_display = ('user', 'input_title', 'size', 'is_show', 'is_calculable', 'formula')

class FontsAdmin(admin.ModelAdmin):
    list_display = ['name']
admin.site.register(Invoice, InvoiceAdmin)
admin.site.register(Font, FontsAdmin)
admin.site.register(Product, ProductAdmin)
admin.site.register(Product_properties, Product_propertiesAdmin)
admin.site.register(new_product_in_frontend, new_product_in_frontendAdmin)

@admin.register(InvoiceExtractionLog)
class InvoiceExtractionLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'status', 'job_id','invoice_type', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('job_id', 'user__username', 'status','invoice_type')


@admin.register(CustomField)
class CustomFieldAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'user', 'company', 'field_type', 'hidden', 'created_time', 'updated_time')
    list_filter = ('field_type', 'hidden', 'created_time')
    search_fields = ('name', 'user__username', 'company__company_name')

