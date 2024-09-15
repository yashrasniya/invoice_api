from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from ..models import User
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated

from django.contrib.auth import authenticate

from ..serializers import RegisterSerializer,user_detail

class Register_user(generics.CreateAPIView):
    permission_classes = [AllowAny]
    serializer_class = RegisterSerializer


class Login(APIView):
    permission_classes = [AllowAny]

    def post(self,request):
        username=request.data.get('username','')
        password=request.data.get('password','')
        if not (username and password):
            return Response({'error':'password is wrong!','status':400},status=400)
        user=authenticate(username=username, password=password)
        if user:
            return Response(user_detail(user).data)
        return Response({'error':'password is wrong!','status':400},status=400)

class Profile(APIView):
    permission_classes = [IsAuthenticated]

    def post(self,request):
        user_detail.update(user_detail(),request.user,validated_data=request.data)

        return Response(user_detail(request.user,context={'request':request}).data)

    def get(self,request):
        return Response(user_detail(request.user,context={'request':request}).data)

