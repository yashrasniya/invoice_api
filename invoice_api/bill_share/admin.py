from django.contrib import admin

from bill_share.models import BillShare


# Register your models here.
@admin.register(BillShare)
class BillShareAdmin(admin.ModelAdmin):
    list_display = ['id','user','invoice','to','created_at', 'type']