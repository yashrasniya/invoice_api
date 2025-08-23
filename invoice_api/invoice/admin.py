from django.contrib import admin
from .models import Invoice, Product, Product_properties, new_product_in_frontend, Font


class InvoiceAdmin(admin.ModelAdmin):
    list_display = ('user', 'invoice_number', 'receiver', 'date', 'gst_final_amount', 'total_final_amount')


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
