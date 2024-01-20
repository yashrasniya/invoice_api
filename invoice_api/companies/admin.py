from django.contrib import admin
from .models import Companies


class CompaniesAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'address', 'gst_number', 'state', 'state_code')


admin.site.register(Companies, CompaniesAdmin)