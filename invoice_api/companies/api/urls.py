from django.urls import path
from .views import CompaniesView, VendorView
urlpatterns = [
    path('companies/', CompaniesView.as_view()),
    path('companies/<int:id>/', CompaniesView.as_view()),
    path('vendors/', VendorView.as_view()),
    path('vendors/<int:id>/', VendorView.as_view()),

]