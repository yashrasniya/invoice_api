from django.urls import path
from .views import Register_user,Login,Profile
urlpatterns = [
    path('register/', Register_user.as_view()),
    path('login/', Login.as_view()),
    path('profile/', Profile.as_view()),
]