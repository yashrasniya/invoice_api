from django.contrib import admin
from .models import WhatsAppIntegration, WhatsAppTemplate, WhatsAppMessage

@admin.register(WhatsAppIntegration)
class WhatsAppIntegrationAdmin(admin.ModelAdmin):
    list_display = ('user', 'business_account_id', 'phone_number_id', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('user__username', 'business_account_id', 'phone_number_id')

@admin.register(WhatsAppTemplate)
class WhatsAppTemplateAdmin(admin.ModelAdmin):
    list_display = ('template_name', 'user', 'category', 'status', 'meta_template_id', 'created_at')
    list_filter = ('category', 'status')
    search_fields = ('template_name', 'user__username', 'meta_template_id')
    actions = ['approve_templates', 'reject_templates']

    def approve_templates(self, request, queryset):
        queryset.update(status='approved')
    approve_templates.short_description = "Mark selected templates as approved"

    def reject_templates(self, request, queryset):
        queryset.update(status='rejected')
    reject_templates.short_description = "Mark selected templates as rejected"

@admin.register(WhatsAppMessage)
class WhatsAppMessageAdmin(admin.ModelAdmin):
    list_display = ('recipient_number', 'user', 'status', 'template_id', 'created_at')
    list_filter = ('status',)
    search_fields = ('recipient_number', 'user__username', 'meta_message_id')
