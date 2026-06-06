from django.urls import path, include
from .views import Register_user, Login, Profile, log_out, ContactUs, UserInfo, UserCompaniesViewSet, LoginByToken, CheckMobileNumber
from rest_framework.routers import DefaultRouter


urlpatterns = [
    path('register/', Register_user.as_view()),
    path('login/', Login.as_view()),
    path('login_token/', LoginByToken.as_view()),
    path('profile/', Profile.as_view()),
    path('log_out/', log_out.as_view()),
    path('user_info/', UserInfo.as_view()),
    path('user-companies/', UserCompaniesViewSet.as_view()),
    path('check-mobile/', CheckMobileNumber.as_view()),
]