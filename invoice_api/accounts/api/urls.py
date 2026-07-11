from django.urls import path, include
from .views import Register_user, Login, GoogleLogin, Profile, log_out, ContactUs, UserInfo, UserCompaniesViewSet, LoginByToken, CheckMobileNumber
from rest_framework.routers import DefaultRouter

from . import views_authz

authz_router = DefaultRouter()
authz_router.register(r'roles', views_authz.RoleViewSet, basename='authz-roles')
authz_router.register(r'groups', views_authz.GroupViewSet, basename='authz-groups')

urlpatterns = [
    # Tenant Admin authz APIs
    path('authz/', include(authz_router.urls)),
    path('authz/permissions/', views_authz.PermissionCatalogView.as_view()),
    path('authz/users/', views_authz.CompanyUsersView.as_view()),
    path('authz/users/<int:user_id>/permissions/', views_authz.UserDirectPermissionView.as_view()),
    path('authz/users/<int:user_id>/permissions/<int:perm_id>/', views_authz.UserDirectPermissionView.as_view()),
    path('authz/users/<int:user_id>/effective-permissions/', views_authz.EffectivePermissionsView.as_view()),
    path('authz/audit-log/', views_authz.CompanyAuditLogView.as_view()),
    path('authz/me/', views_authz.MyAccessView.as_view()),

    path('register/', Register_user.as_view()),
    path('login/', Login.as_view()),
    path('google-login/', GoogleLogin.as_view()),
    path('login_token/', LoginByToken.as_view()),
    path('profile/', Profile.as_view()),
    path('log_out/', log_out.as_view()),
    path('user_info/', UserInfo.as_view()),
    path('user-companies/', UserCompaniesViewSet.as_view()),
    path('check-mobile/', CheckMobileNumber.as_view()),
]