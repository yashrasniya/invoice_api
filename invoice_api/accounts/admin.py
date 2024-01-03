from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User,Superuser,CR
from .utils import actions
from django.db.models import Q

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




