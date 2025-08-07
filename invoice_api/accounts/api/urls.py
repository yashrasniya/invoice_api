from django.urls import path
from .views import Register_user, Login, Profile, log_out, ContactUs

urlpatterns = [
    path('register/', Register_user.as_view()),
    path('login/', Login.as_view()),
    path('profile/', Profile.as_view()),
    path('log_out/', log_out.as_view()),
]