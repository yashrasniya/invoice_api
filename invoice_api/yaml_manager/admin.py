from django.contrib import admin
from yaml_manager.models import Yaml


# Register your models here.
@admin.register(Yaml)
class yamlAdmin(admin.ModelAdmin):
    pass