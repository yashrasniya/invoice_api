import logging

from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from invoice.models import Invoice, new_product_in_frontend
from yaml_manager.models import Yaml
from ..authenticate import ServiceTokenAuthentication, AdminJWTTokenAuthentication
from ..models import UserCompanies
from rest_framework import generics
from rest_framework.permissions import IsAuthenticated
from rest_framework import viewsets, mixins

from django.contrib.auth import authenticate
from django.conf import settings
from django.utils import timezone
from django.db import transaction
from django.core.files import File
from google.oauth2 import id_token as google_id_token
from google.auth.transport import requests as google_requests
import os

from accounts.audit import audit_session
from accounts.serializers.serializers import RegisterSerializer,user_detail
from django.middleware import csrf

from accounts.serializers.UserCompanies import UserCompaniesSerializer

logging = logging.getLogger(__name__)
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
            logging.info(f"{username} wrong password")
            return Response({'error':'password is wrong!','status':400},status=400)
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
            logging.info(f"{username} login")
            audit_session(user, 'LOGIN', request, {'method': 'password'})
            return response

        # Check for Google login hint if password auth fails
        from django.contrib.auth import get_user_model
        from django.db.models import Q
        User = get_user_model()
        existing_user = User.objects.filter(Q(username=username) | Q(email__iexact=username)).first()
        if existing_user and not existing_user.has_usable_password() and existing_user.social_accounts.filter(provider='google').exists():
            logging.info(f"{username} login failed: account uses Google Sign-In")
            return Response({'error': 'This account uses Google Sign-In.', 'status': 400}, status=400)

        if existing_user:
            audit_session(existing_user, 'LOGIN_FAILED', request, {'method': 'password'})
        logging.info(f"{username} wrong password")
        return Response({'error':'password is wrong!','status':400},status=400)

class GoogleLogin(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []          # pure credential exchange, no prior auth

    def post(self, request):
        credential = request.data.get('credential')
        if not credential:
            return Response({'error': 'Missing Google credential.'}, status=400)

        # 1. Verify token: signature (Google public keys), exp, iss, aud
        try:
            claims = google_id_token.verify_oauth2_token(
                credential,
                google_requests.Request(),
                settings.GOOGLE_OAUTH_CLIENT_ID,
                clock_skew_in_seconds=10,
            )
        except ValueError:
            logging.warning("Google login: invalid ID token")
            return Response({'error': 'Invalid or expired Google token.'}, status=401)

        if not claims.get('email_verified'):
            return Response({'error': 'Google account email is not verified.'}, status=403)

        sub = claims['sub']
        email = claims.get('email', '')

        # 2. Resolve user: sub match → email link → create
        user, created = self._get_or_create_user(sub, email, claims)
        if user is None:
            return Response({'error': 'This account is disabled.'}, status=403)

        # 3. Issue the SAME cookie as the password Login view
        response = Response()
        data = get_tokens_for_user(user)
        response.set_cookie(
            key=settings.SIMPLE_JWT['AUTH_COOKIE'],
            value=data["access"],
            expires=settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'],
            secure=settings.SIMPLE_JWT['AUTH_COOKIE_SECURE'],
            httponly=settings.SIMPLE_JWT['AUTH_COOKIE_HTTP_ONLY'],
            samesite=settings.SIMPLE_JWT['AUTH_COOKIE_SAMESITE'],
        )
        csrf.get_token(request)
        body = user_detail(user).data
        body['created'] = created            # frontend can use this to route new users to company setup
        response.data = body
        logging.info(f"{user.username} login via Google ({'new user' if created else 'existing'})")
        audit_session(user, 'LOGIN', request, {'method': 'google', 'created': created})
        return response

    def _get_or_create_user(self, sub, email, claims):
        from django.contrib.auth import get_user_model
        from accounts.models import SocialAccount
        User = get_user_model()

        with transaction.atomic():
            # a) Already linked
            social = (SocialAccount.objects
                      .select_related('user')
                      .filter(provider='google', provider_uid=sub)
                      .first())
            if social:
                if not social.user.is_active:
                    return None, False
                social.last_login_at = timezone.now()
                social.email = email
                social.save(update_fields=['last_login_at', 'email'])
                return social.user, False

            # b) Existing account with same (verified) email → link
            user = User.objects.filter(email__iexact=email).first() if email else None
            created = False

            # c) No account → create
            if user is None:
                username = self._unique_username(User, email)
                
                # Perform creation with template files initialization mimicking RegisterSerializer
                file_path = os.path.join(settings.BASE_DIR, "static", "default_template.yaml")
                
                user = User(
                    username=username,
                    email=email,
                    first_name=claims.get('given_name', '')[:150],
                    last_name=claims.get('family_name', '')[:150],
                    is_active=True,
                    is_company_admin=True,
                )
                user.set_unusable_password()   # no password login until user sets one
                user.save()
                
                # Create default yaml template
                if os.path.exists(file_path):
                    with open(file_path, 'rb') as f:
                        Yaml.objects.create(
                            yaml_file=File(f, name="default_template.yaml"),
                            user=user,
                        )
                else:
                    logging.warning("default_template.yaml not found at static root.")
                
                # Create default product fields
                new_product_in_frontend.objects.create(user=user, input_title='Description', size=3, is_calculable=False, is_show=True)
                new_product_in_frontend.objects.create(user=user, input_title='Quantity', size=3, is_calculable=True, is_show=True)
                new_product_in_frontend.objects.create(user=user, input_title='Rate', size=3, is_calculable=True, is_show=True)
                new_product_in_frontend.objects.create(user=user, input_title='GST', size=3, is_calculable=True, is_show=True)
                
                created = True

            if not user.is_active:
                return None, False

            SocialAccount.objects.create(
                user=user, provider='google', provider_uid=sub,
                email=email, picture_url=claims.get('picture', ''),
            )
            return user, created

    @staticmethod
    def _unique_username(User, email):
        base = (email.split('@')[0] if email else 'google_user')[:140] or 'google_user'
        username, i = base, 0
        while User.objects.filter(username=username).exists():
            i += 1
            username = f"{base}{i}"
        return username


class log_out(APIView):
    permission_classes = (IsAuthenticated,)
    def get(self,request):
        logging.info(f"{request.user.username} Is logout")
        audit_session(request.user, 'LOGOUT', request)
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
        s = user_detail(request.user, data=request.data, partial=True)
        s.is_valid(raise_exception=True)
        s.save()
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


class UserInfo(APIView):
    """Dashboard KPI header.

    Sales/GST totals cover *sales* invoices only (purchases are excluded so
    they can no longer inflate revenue), and growth percentages are `None`
    when the comparison period has no data, rather than a fabricated number
    derived from a placeholder denominator.
    """
    permission_classes = [IsAuthenticated]

    EMPTY = {
        'month_total_final_amount': 0, 'month_gst_final_amount': 0,
        'prv_total_final_amount': 0, 'prv_gst_final_amount': 0,
        'percentage_change': None, 'percentage_gst_amount': None,
        'invoices_this_month_count': 0, 'invoices_prv_month_count': 0,
        'receivable_amount': 0, 'receivable_count': 0,
        'overdue_amount': 0, 'overdue_count': 0, 'overdue_after_days': 0,
        'range': 'this_month', 'range_label': '', 'has_any_invoice': False,
    }

    def get(self, request):
        from invoice_api.dashboard import (
            period_bounds, pct_change, sales_totals, outstanding_totals)
        from invoice_api.scoping import user_scope_q

        name = str(request.user.name())

        # no invoice.view → no invoice KPIs (return zeros, keep the name)
        if 'invoice.view' not in (getattr(request, 'permissions', None) or set()):
            return Response({'name': name, **self.EMPTY})

        rng = request.query_params.get('range') or 'this_month'
        (start, end), (prev_start, prev_end), label = period_bounds(rng)

        scope = user_scope_q(request)
        base = Invoice.objects.filter(scope, invoice_type='sales')

        cur = sales_totals(base, start, end)
        prv = sales_totals(base, prev_start, prev_end)
        outstanding = outstanding_totals(base)
        # "have they ever billed anything" drives the first-run screen, so
        # ask across all invoice types — a purchase-only tenant is not a
        # brand-new account and shouldn't be shown the onboarding empty state
        has_any = Invoice.objects.filter(scope).exists()

        return Response({
            "name": name,
            "range": rng,
            "range_label": label,
            "month_total_final_amount": cur['total'],
            "month_gst_final_amount": cur['gst'],
            "prv_total_final_amount": prv['total'],
            "prv_gst_final_amount": prv['gst'],
            # None (not 0, not a fake %) when there is nothing to compare to
            "percentage_change": pct_change(cur['total'], prv['total']),
            "percentage_gst_amount": pct_change(cur['gst'], prv['gst']),
            "invoices_this_month_count": cur['count'],
            "invoices_prv_month_count": prv['count'],
            **outstanding,
            "has_any_invoice": has_any,
        })

class UserCompaniesViewSet(
    APIView
):
    queryset = UserCompanies.objects.all()
    serializer_class = UserCompaniesSerializer

    def post(self,request):
        if request.user.user_company:
            # editing an existing company profile is admin-only; creating a
            # first company (onboarding) is open to any authenticated user
            is_admin = (request.user.is_company_admin or
                        'role.manage' in (getattr(request, 'permissions', None) or set()))
            if not is_admin:
                return Response({'detail': 'Only a company admin can edit the company profile.',
                                 'code': 'permission_denied'},
                                status=status.HTTP_403_FORBIDDEN)
            serializer = UserCompaniesSerializer(request.user.user_company,data=request.data)
        else:
            serializer = UserCompaniesSerializer(data=request.data)
        if serializer.is_valid():
            company = serializer.save()

            # Link company to current user
            user = request.user
            yaml_obj = Yaml.objects.filter(user__id=request.user.id).first()
            if yaml_obj:
                yaml_obj.company = company
                yaml_obj.save()
            user.user_company = company
            company.is_varified = True
            company.save()
            user.save()

            return Response({
                "message": "Company created and linked to user",
                "company": serializer.data
            }, status=status.HTTP_201_CREATED)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def get(self,request):
        if request.user.user_company and request.user.is_company_admin:
            return  Response(UserCompaniesSerializer(request.user.user_company, context={"request": request}).data)
        return Response()

class LoginByToken(APIView):

    authentication_classes = [ServiceTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        username = request.user.username
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
        logging.info(f"{username} login by token")
        audit_session(user, 'LOGIN', request, {'method': 'service_token'})
        return response


def normalize_mobile(mobile):
    if not mobile:
        return ""
    # Retain only digits and '+'
    mobile = "".join(c for c in str(mobile) if c.isdigit() or c == "+")
    
    # 1. Remove +91 prefix
    if mobile.startswith("+91"):
        mobile = mobile[3:]
    # 2. Remove 91 prefix if total length is > 10
    elif mobile.startswith("91") and len(mobile) > 10:
        mobile = mobile[2:]
        
    # 3. If more than 10 characters and starts with 0, remove the leading 0s
    while len(mobile) > 10 and mobile.startswith("0"):
        mobile = mobile[1:]
        
    return mobile


class CheckMobileNumber(APIView):
    authentication_classes = [AdminJWTTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        mobile = request.query_params.get('mobile_number') or request.query_params.get('mobile')
        return self._check_mobile(mobile)

    def post(self, request):
        mobile = request.data.get('mobile_number') or request.data.get('mobile')
        return self._check_mobile(mobile)

    def _check_mobile(self, mobile):
        if not mobile:
            return Response({'error': 'Mobile number is required.'}, status=status.HTTP_400_BAD_REQUEST)
        
        from django.contrib.auth import get_user_model
        User = get_user_model()
        
        normalized_input = normalize_mobile(mobile)
        if not normalized_input:
            return Response({'error': 'Invalid mobile number format.'}, status=status.HTTP_400_BAD_REQUEST)
            
        # Match using last 8 digits for DB index performance, then exact normalize comparison in python
        suffix = normalized_input[-8:]
        candidates = User.objects.filter(mobile_number__endswith=suffix)
        
        matched_user = None
        for u in candidates:
            if normalize_mobile(u.mobile_number) == normalized_input:
                matched_user = u
                break
                
        if matched_user:
            return Response({
                'present': True, 
                'mobile_number': mobile, 
                'normalized_number': normalized_input,
                'id': matched_user.id
            }, status=status.HTTP_200_OK)
            
        return Response({
            'present': False, 
            'mobile_number': mobile,
            'normalized_number': normalized_input
        }, status=status.HTTP_404_NOT_FOUND)



