import os
import threading
import logging

from django.conf import settings
from django.core.files import File
from rest_framework import serializers
from rest_framework.validators import UniqueValidator
from django.contrib.auth.password_validation import validate_password
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.mobile import clean_indian_mobile
from accounts.models import SocialAccount, User
from accounts.phone_verify import PhoneTokenError, verify_phone_id_token
from accounts.usernames import unique_username
from invoice.models import new_product_in_frontend
from invoice_api.utilitys import image_add_db
from django.core.mail import send_mail

from yaml_manager.models import Yaml
logger = logging.getLogger(__name__)


class RegisterSerializer(serializers.ModelSerializer):
    # optional: derived from the email when omitted, so signup doesn't ask for it
    username = serializers.CharField(
        required=False,
        validators=[UniqueValidator(queryset=User.objects.all())]
    )
    email = serializers.EmailField(
        required=True,
        validators=[UniqueValidator(queryset=User.objects.all(), lookup='iexact',
                                    message='An account with this email already exists.')]
    )
    password = serializers.CharField(
        write_only=True, required=True, validators=[validate_password])
    # declared here (not auto-generated) so the model's 12 character cap doesn't reject '+91 98765 43210' before
    # validate_mobile_number() normalises it
    mobile_number = serializers.CharField(required=True)
    # optional proof from the app's SMS check; when it vouches for this number the account starts mobile-verified
    phone_id_token = serializers.CharField(write_only=True, required=False, allow_blank=True)
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
            'token',
            'phone_id_token',
        )
        extra_kwargs = {
            'first_name': {'required': True},
            'last_name': {'required': False, 'allow_blank': True},
            'mobile_number': {'required': True},
        }

    def get_token(self, obj):
        return str(RefreshToken.for_user(obj))

    def validate_mobile_number(self, value):
        # '+91 98765 43210' and '098765-43210' are the same number; store it the way the rest of the app compares it
        number = clean_indian_mobile(value)
        if number is None:
            raise serializers.ValidationError('Enter a valid 10 digit mobile number.')
        return number

    def validate(self, attrs):
        proof = attrs.pop('phone_id_token', '')
        attrs['_phone_proof'] = None
        if proof:
            try:
                uid, verified = verify_phone_id_token(proof)
            except PhoneTokenError as e:
                raise serializers.ValidationError({'phone_id_token': e.message})
            if verified != attrs['mobile_number']:
                raise serializers.ValidationError({'phone_id_token': 'That code was sent to a different number.'})
            attrs['_phone_proof'] = uid
        return attrs

    def create(self, validated_data):
        file_path = os.path.join(settings.BASE_DIR, "static", "default_template.yaml")

        with open(file_path, 'rb') as f:
            user = User.objects.create(
                email=validated_data['email'],
                first_name=validated_data['first_name'],
                last_name=validated_data.get('last_name', ''),
                mobile_number=validated_data['mobile_number'],
                username=validated_data.get('username') or unique_username(User, validated_data['email']),
                mobile_verified=validated_data['_phone_proof'] is not None,
            )
            user.is_active = True
            user.is_company_admin = True
            user.set_password(validated_data['password'])
            user.save()
            Yaml.objects.create(
                yaml_file=File(f, name="default_template.yaml"),  # attach file
                user=user,
                # first template of a brand-new account is the company default,
                # so nothing has to be picked before the first PDF export
                is_default=True,
            )

        new_product_in_frontend.objects.create(user= user,input_title='Description',size=3,is_calculable=False,is_show=True)
        new_product_in_frontend.objects.create(user= user,input_title='Quantity',size=3,is_calculable=True,is_show=True)
        new_product_in_frontend.objects.create(user= user,input_title='Rate',size=3,is_calculable=True,is_show=True)
        new_product_in_frontend.objects.create(user= user,input_title='GST',size=3,is_calculable=True,is_show=True)

        if validated_data['_phone_proof'] is not None:
            # same link a phone login would have made, so signing in by SMS later lands in this account
            SocialAccount.objects.get_or_create(
                provider='phone', provider_uid=validated_data['_phone_proof'], defaults={'user': user})

        logger.info(f"New user created {user.username}")
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
            'email_verified',
            'mobile_verified',
            # 'token',

        )
        # ownership proofs are earned, never self-declared through the profile endpoint
        read_only_fields = ('email_verified', 'mobile_verified')
    # def get_token(self, obj):
    #     return str(RefreshToken.for_user(obj))

    def update(self, instance, validated_data):
        read_only = ['id', 'email', 'profile']
        image_add_db({'profile': instance.profile}, validated_data, instance=instance)
        # validated_data._mutable=True
        for i in read_only:
            if validated_data.get(i, ''):
                validated_data.pop(i)
        return super().update(instance, validated_data)
