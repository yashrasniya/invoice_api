from django.urls import path, include
from rest_framework.routers import DefaultRouter

from .views import CompaniesView, VendorView
from . import views_admin

admin_router = DefaultRouter()
admin_router.register(r'plans', views_admin.PlanViewSet, basename='admin-plans')
admin_router.register(r'features', views_admin.FeatureViewSet, basename='admin-features')

urlpatterns = [
    # Product Owner platform APIs
    path('admin/', include(admin_router.urls)),
    path('admin/companies/', views_admin.CompanyListView.as_view()),
    path('admin/companies/<int:company_id>/subscription/', views_admin.CompanySubscriptionAdminView.as_view()),
    path('admin/audit-log/', views_admin.PlatformAuditLogView.as_view()),
    path('admin/whatsapp-account/', views_admin.PlatformWhatsAppAccountView.as_view()),

    path('companies/', CompaniesView.as_view()),
    path('companies/<int:id>/', CompaniesView.as_view()),
    path('vendors/', VendorView.as_view()),
    path('vendors/<int:id>/', VendorView.as_view()),

]