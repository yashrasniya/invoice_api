from django.contrib import admin, messages
from django.contrib.admin import helpers
from django.template.response import TemplateResponse
from django.contrib.auth.admin import UserAdmin
from .models import User, Superuser, CR, UserCompanies
from .utils import actions
from . import deletion
from django.db.models import Q
from .models import ServiceToken

# Register your models here.

@admin.action(description="Permanently delete accounts that asked to be deleted")
def purge_requested_accounts(modeladmin, request, queryset):
    """Real delete of the user and everything they created (invoices, customers, vendors, ...), plus their company
    if nobody else is in it. Only touches users who asked to be deleted; superusers are always skipped."""
    done, skipped = [], 0
    for user in queryset:
        try:
            done.append(deletion.purge_user(user))
        except ValueError:
            skipped += 1
    if done:
        modeladmin.message_user(request, f"Permanently deleted: {', '.join(done)}", messages.SUCCESS)
    if skipped:
        modeladmin.message_user(request, f"{skipped} selected user(s) skipped: they have not asked to be deleted.", messages.WARNING)


@admin.action(description="PERMANENTLY delete user + their entire company and all data (irreversible)")
def purge_user_and_company(modeladmin, request, queryset):
    """Shows a warning page listing what will be destroyed; only deletes after the admin confirms."""
    if request.POST.get('confirm_full_purge'):
        done = []
        for user in queryset:
            try:
                done.append(deletion.purge_user_and_company(user))
            except ValueError as e:
                modeladmin.message_user(request, f"Skipped: {e}", messages.WARNING)
        if done:
            modeladmin.message_user(request, f"Permanently deleted: {'; '.join(done)}", messages.SUCCESS)
        return None
    items = []
    for user in queryset.select_related('user_company'):
        company = user.user_company
        items.append({
            'user': user,
            'company': company,
            'members': list(company.user_set.all()) if company else [user],
            'blocked': user.is_superuser or bool(company and company.user_set.filter(is_superuser=True).exists()),
        })
    context = {
        **modeladmin.admin_site.each_context(request),
        'title': 'Permanently delete users and their companies',
        'items': items,
        'queryset': queryset,
        'opts': modeladmin.model._meta,
        'action_checkbox_name': helpers.ACTION_CHECKBOX_NAME,
        'action_name': 'purge_user_and_company',
    }
    return TemplateResponse(request, 'admin/accounts/user/purge_confirmation.html', context)


@admin.register(User)
class UserAdmin(actions,UserAdmin):
    actions = list(getattr(actions, 'actions', []) or []) + [purge_requested_accounts, purge_user_and_company]
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (("Personal info"), {"fields": ("first_name", "last_name", "email",'gender','profile','dob')}),
        (
            ("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    # "user_permissions",
                ),
            })
            ,
        (
             ("Contect"),
        {
            "fields": (
                "mobile_number",
                "user_company",
                "is_company_admin",

            ),
        }),

        (("Account deletion"), {"fields": ("deletion_requested_at",)}),
        # (("Important dates"), {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2"),
            },
        ),
    )
    list_filter=['is_staff','gender','date_joined', ('deletion_requested_at', admin.EmptyFieldListFilter)]
    search_fields = [
        'mobile_number',
        'username',
        'email',

        'dob',

    ]
    list_display = ("username", "name", "email", 'date_joined', 'deletion_requested_at')
    ordering = ("username",)
    # def get_queryset(self, request):
    #     return self.model.objects.filter(is_superuser=False)



@admin.register(UserCompanies)
class UserCompaniesAdmin(admin.ModelAdmin):
    list_display = ['company_name','is_varified']


@admin.register(ServiceToken)
class ServiceTokenAdmin(admin.ModelAdmin):
    # Columns to display in the list view
    list_display = ('name', 'user', 'is_active', 'created_at', 'token')

    # Add search and filtering capabilities
    search_fields = ('name', 'token', 'user__username', 'user__email')
    list_filter = ('is_active', 'created_at')

    # Prevent creating new tokens via the admin panel
    def has_add_permission(self, request):
        return False

    # Prevent modifying existing tokens via the admin panel
    def has_change_permission(self, request, obj=None):
        return False

    # Prevent deleting tokens via the admin panel
    # (If you want super admins to be able to delete them, you can remove this method)
    def has_delete_permission(self, request, obj=None):
        return False

    # As long as you don't override has_view_permission to return False,
    # Django will automatically allow super admins to click into the object
    # and view all fields in a read-only state.