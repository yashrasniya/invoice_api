from django.contrib import admin
from yaml_manager.models import Yaml, YamlVersion


# Register your models here.
@admin.register(Yaml)
class yamlAdmin(admin.ModelAdmin):
    list_display = ['template_name','user','company']

@admin.register(YamlVersion)
class YamlVersionAdmin(admin.ModelAdmin):
    list_display = ['yaml', 'created_at']
    readonly_fields = ['created_at']