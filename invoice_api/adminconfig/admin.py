from django.contrib import admin
from django.contrib import messages
from django.utils.html import format_html
from .models import Xl_download_config, AdminJWTToken

# Register your models here.

admin.site.register(Xl_download_config)

@admin.register(AdminJWTToken)
class AdminJWTTokenAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'created_at', 'is_active')
    search_fields = ('name', 'user__username', 'user__first_name', 'user__last_name')
    list_filter = ('is_active', 'created_at')

    def get_fields(self, request, obj=None):
        if obj is None:
            return ('name', 'user', 'is_active')
        return ('name', 'user', 'is_active', 'created_at')

    def get_readonly_fields(self, request, obj=None):
        if obj:
            return ('name', 'user', 'created_at')
        return ()

    def save_model(self, request, obj, form, change):
        is_new = obj.pk is None
        super().save_model(request, obj, form, change)
        if is_new and obj.token:
            messages.success(
                request,
                format_html(
                    '<div style="background: #1e1e2e; color: #cdd6f4; border: 1px solid #cba6f7; padding: 16px; border-radius: 8px; margin-top: 10px; font-family: sans-serif;">'
                    '    <strong style="color: #a6e3a1; font-size: 15px; display: block; margin-bottom: 8px;">'
                    '        ✔ JWT Token Generated Successfully!'
                    '    </strong>'
                    '    <p style="margin: 0 0 12px 0; font-size: 13px; color: #a6adc8;">'
                    '        Copy the token below now. For security reasons, <strong>it will not be shown again</strong>.'
                    '    </p>'
                    '    <div style="display: flex; gap: 10px; align-items: center;">'
                    '        <input id="jwt-token-input" readonly value="{}" style="flex-grow: 1; font-family: monospace; font-size: 13px; padding: 10px; border: 1px solid #45475a; border-radius: 6px; background-color: #313244; color: #f5c2e7; outline: none;" />'
                    '        <button type="button" onclick="navigator.clipboard.writeText(document.getElementById(\'jwt-token-input\').value); this.innerText=\'Copied!\'; this.style.backgroundColor=\'#a6e3a1\'; this.style.color=\'#11111b\';" '
                    '                style="padding: 10px 16px; cursor: pointer; background-color: #cba6f7; color: #11111b; border: none; border-radius: 6px; font-weight: bold; font-size: 13px; transition: all 0.2s ease;">'
                    '            Copy Token'
                    '        </button>'
                    '    </div>'
                    '</div>',
                    obj.token
                )
            )

