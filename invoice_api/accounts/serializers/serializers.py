import threading
import logging

from django.conf import settings
from django.core.files import File
from rest_framework import serializers
from rest_framework.validators import UniqueValidator
from django.contrib.auth.password_validation import validate_password
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from invoice.models import new_product_in_frontend
from invoice_api.utilitys import image_add_db
from django.core.mail import send_mail

from yaml_manager.models import Yaml
logger = logging.getLogger(__name__)


class RegisterSerializer(serializers.ModelSerializer):
    username = serializers.CharField(
        required=True,
        validators=[UniqueValidator(queryset=User.objects.all())]
    )
    password = serializers.CharField(
        write_only=True, required=True, validators=[validate_password])
    status = serializers.IntegerField(default=200,read_only=True)
    token = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'email',
            'username',
            'password',
            'first_name',
            'last_name',
            'mobile_number',
            'status',
            'token'
        )
        extra_kwargs = {
            'first_name': {'required': True},
            'last_name': {'required': True},
            'email': {'required': True},
            'mobile_number': {'required': True},
        }

    def get_token(self, obj):
        return str(RefreshToken.for_user(obj))

    async  def send_email(self, email, name, mobile_number):
        subject = f"New User Register  {name}"
        email_message = f"""
                        Name: {name}
                        Email: {email}
                        Mobile Number: {mobile_number}
                        """
        recipient_list = [email]

        result = send_mail(subject, email_message, settings.DEFAULT_FROM_EMAIL, recipient_list)
        if result:
            logging.info("email sent")
        else:
            logging.error("email not sent")

    def create(self, validated_data):
        user = User.objects.create(
            email=validated_data['email'],
            first_name=validated_data['first_name'],
            last_name=validated_data['last_name'],
            mobile_number=validated_data['mobile_number'],
            username=validated_data['username'],
        )
        user.is_active = True
        user.is_company_admin = True
        user.set_password(validated_data['password'])
        user.save()
        with open('static/default_template.yaml', 'rb') as f:
            Yaml.objects.create(
                yaml_file=File(f, name="default_template.yaml"),  # attach file
                user=user
            )
        new_product_in_frontend.objects.create(user= user,input_title='Description',size=3,is_calculable=False,is_show=True)
        new_product_in_frontend.objects.create(user= user,input_title='Quantity',size=3,is_calculable=True,is_show=True)
        new_product_in_frontend.objects.create(user= user,input_title='Rate',size=3,is_calculable=True,is_show=True)
        new_product_in_frontend.objects.create(user= user,input_title='GST',size=3,is_calculable=True,is_show=True)

        threading.Thread(
            target=self.send_email,
            args=(
                validated_data['email'],
                validated_data['first_name'],
                validated_data['mobile_number'],
            ),
            daemon=True
        ).start()

        logger.info(f"New user created {validated_data['username']}")
        return user

class User_PublicSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = (
            'username',
            'name',
            'profile'
        )

class user_detail(serializers.ModelSerializer):
    email = serializers.EmailField(read_only=True)
    first_name = serializers.CharField(read_only=True)
    last_name = serializers.CharField(read_only=True)
    status = serializers.IntegerField(default=200)
    # token = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            'email',
            'username',
            'first_name',
            'last_name',
            'name',
            'gender',
            'mobile_number',
            'status',
            'profile',
            'is_company_varified',
            'is_company_admin',
            'dob',
            'is_superuser',
            'is_staff',
            # 'token',

        )
    # def get_token(self, obj):
    #     return str(RefreshToken.for_user(obj))

    def update(self, instance, validated_data):
        read_only = ['id', 'email', 'profile']
        image_add_db({'profile': instance.profile}, validated_data, instance=instance)
        # validated_data._mutable=True
        for i in read_only:
            if validated_data.get(i, ''):
                validated_data.pop(i)
        print(type(validated_data))
        super().update(instance, validated_data)
