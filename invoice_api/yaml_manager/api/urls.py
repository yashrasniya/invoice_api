from django.urls import path

from yaml_manager.api.views import YamlView, YamlListView, ImageUploadView

urlpatterns = [
    path('yaml/',YamlView.as_view()),
    path('yaml/list/',YamlListView.as_view()),
    path('upload_image/', ImageUploadView.as_view()),
]