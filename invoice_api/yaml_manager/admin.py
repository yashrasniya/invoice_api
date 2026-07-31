from django.contrib import admin
from yaml_manager.models import Yaml, YamlVersion


# Register your models here.
@admin.register(Yaml)
class yamlAdmin(admin.ModelAdmin):
    list_display = ['template_name', 'user', 'company', 'is_html', 'is_global', 'global_category', 'is_default']
    list_filter = ['is_global', 'is_html', 'global_category', 'is_default']
    list_editable = ['is_global', 'global_category']
    search_fields = ['template_name', 'user__username', 'company__company_name']

@admin.register(YamlVersion)
class YamlVersionAdmin(admin.ModelAdmin):
    list_display = ['yaml', 'created_at']
    readonly_fields = ['created_at']