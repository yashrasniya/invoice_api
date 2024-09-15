from django.urls import path
from .views import CompaniesView
urlpatterns = [
    path('companies/', CompaniesView.as_view()),
    path('companies/<int:id>/', CompaniesView.as_view()),

]