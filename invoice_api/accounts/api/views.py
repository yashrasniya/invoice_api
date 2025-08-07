from django.conf import settings
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from ..models import User
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from django.contrib.auth import authenticate

from ..serializers import RegisterSerializer,user_detail
from django.middleware import csrf


class Register_user(generics.CreateAPIView):
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer

def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        'refresh': str(refresh),
        'access': str(refresh.access_token),
    }

class Login(APIView):
    permission_classes = [AllowAny]

    def post(self,request):
        username=request.data.get('username','')
        password=request.data.get('password','')
        if not (username and password):
            return Response({'error':'password is wrong!','status':400},status=400)
        print(username,password)
        user=authenticate(username=username, password=password)
        if user:
            response = Response()
            data = get_tokens_for_user(user)
            response.set_cookie(
                key=settings.SIMPLE_JWT['AUTH_COOKIE'],
                value=data["access"],
                expires=settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'],
                secure=settings.SIMPLE_JWT['AUTH_COOKIE_SECURE'],
                httponly=settings.SIMPLE_JWT['AUTH_COOKIE_HTTP_ONLY'],
                samesite=settings.SIMPLE_JWT['AUTH_COOKIE_SAMESITE']
            )
            csrf.get_token(request)
            response.data = user_detail(user).data
            return response
        return Response({'error':'password is wrong!','status':400},status=400)

class log_out(APIView):
    permission_classes = (IsAuthenticated,)
    def get(self,request):
        response = Response()
        response.set_cookie(
            key=settings.SIMPLE_JWT['AUTH_COOKIE'],
            value='',
            expires=settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'],
            secure=settings.SIMPLE_JWT['AUTH_COOKIE_SECURE'],
            httponly=settings.SIMPLE_JWT['AUTH_COOKIE_HTTP_ONLY'],
            samesite=settings.SIMPLE_JWT['AUTH_COOKIE_SAMESITE']
        )

        return response

class Profile(APIView):
    permission_classes = [IsAuthenticated]

    def post(self,request):
        user_detail.update(user_detail(),request.user,validated_data=request.data)

        return Response(user_detail(request.user,context={'request':request}).data)

    def get(self,request):
        return Response(user_detail(request.user,context={'request':request}).data)


from django.core.mail import send_mail
from django.conf import settings

class ContactUs(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email')
        name = request.data.get('name')
        mobile_number = request.data.get('mobile_number')
        message = request.data.get('message', '')

        if not all([email, name, mobile_number]):
            return Response({'error': 'Email, name, and mobile number are required.'}, status=status.HTTP_400_BAD_REQUEST)

        subject = f"Contact Us Inquiry from {name}"
        email_message = f"""
        Name: {name}
        Email: {email}
        Mobile Number: {mobile_number}
        Message: {message}
        """
        recipient_list = [settings.DEFAULT_FROM_EMAIL]  # Or a specific contact email address

        try:
            send_mail(subject, email_message, settings.DEFAULT_FROM_EMAIL, recipient_list, fail_silently=False)
            return Response({'success': 'Your message has been sent successfully.'}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({'error': f'Failed to send email: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
