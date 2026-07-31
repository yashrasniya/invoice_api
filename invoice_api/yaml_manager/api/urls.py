from django.urls import path

from yaml_manager.api.views import (
    YamlView, YamlListView, ImageUploadView, WeasyprintPreviewView,
    YamlSetDefaultView, GlobalTemplateGalleryView, CloneGlobalTemplateView,
    YamlTogglePublishView, YamlMetadataUpdateView,
    AdminGlobalTemplateListView, AdminGlobalTemplateDetailView
)

urlpatterns = [
    path('yaml/',YamlView.as_view()),
    path('yaml/list/',YamlListView.as_view()),
    path('yaml/<int:id>/set-default/', YamlSetDefaultView.as_view()),
    path('yaml/<int:id>/toggle-publish/', YamlTogglePublishView.as_view()),
    path('yaml/<int:id>/metadata/', YamlMetadataUpdateView.as_view()),
    path('yaml/admin-list/', AdminGlobalTemplateListView.as_view()),
    path('yaml/admin-detail/<int:id>/', AdminGlobalTemplateDetailView.as_view()),
    path('yaml/gallery/', GlobalTemplateGalleryView.as_view()),
    path('yaml/gallery/<int:id>/clone/', CloneGlobalTemplateView.as_view()),
    path('upload_image/', ImageUploadView.as_view()),
    path('weasyprint_preview/', WeasyprintPreviewView.as_view()),
]