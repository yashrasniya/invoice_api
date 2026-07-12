from django.urls import path

from yaml_manager.api.views import YamlView, YamlListView, ImageUploadView, WeasyprintPreviewView, YamlSetDefaultView

urlpatterns = [
    path('yaml/',YamlView.as_view()),
    path('yaml/list/',YamlListView.as_view()),
    path('yaml/<int:id>/set-default/', YamlSetDefaultView.as_view()),
    path('upload_image/', ImageUploadView.as_view()),
    path('weasyprint_preview/', WeasyprintPreviewView.as_view()),
]