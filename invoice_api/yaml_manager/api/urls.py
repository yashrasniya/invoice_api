from django.urls import path

from yaml_manager.api.views import YamlView

urlpatterns = [
    path('yaml/',YamlView.as_view()),
]