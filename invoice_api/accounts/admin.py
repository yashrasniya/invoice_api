from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Superuser, CR, UserCompanies
from .utils import actions
from django.db.models import Q
from .models import ServiceToken

# Register your models here.

@admin.register(User)
class UserAdmin(actions,UserAdmin):
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
    list_filter=['is_staff','gender','date_joined']
    search_fields = [
        'roll_number',
        'username',
        'email',

        'dob',

    ]
    list_display = ("username", "name",'date_joined')
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