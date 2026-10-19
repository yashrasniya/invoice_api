import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.middleware import csrf
from django.utils import timezone
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.audit import audit_session
from accounts.models import SocialAccount
from accounts.phone_verify import PhoneTokenError, verify_phone_id_token
from accounts.serializers.serializers import user_detail
from accounts.usernames import unique_username

from .views import create_user_with_defaults, get_tokens_for_user, normalize_mobile

logger = logging.getLogger(__name__)


class PhoneLogin(APIView):
    """Exchange a Firebase phone-auth ID token for our own session.

    The app does the SMS OTP step with Firebase; Firebase vouches for the number in the ID token it returns.
    An account that already has the same number is signed in (and linked); otherwise one is created.
    """
    permission_classes = [AllowAny]
    authentication_classes = []          # pure credential exchange, no prior auth

    def post(self, request):
        id_token = request.data.get('id_token')
        if not id_token:
            return Response({'error': 'Missing Firebase ID token.'}, status=400)
        # 1. Verify: signature, expiry, audience, provider — and learn the number Firebase vouches for
        try:
            uid, mobile = verify_phone_id_token(id_token)
        except PhoneTokenError as e:
            return Response({'error': e.message}, status=e.status)

        # 2. Resolve user: Firebase uid match → same phone number → create
        user, created = self._get_or_create_user(uid, mobile)
        if user is None:
            return Response({'error': 'This account has been deleted or disabled.'}, status=403)

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
        body['created'] = created            # app routes new users to company setup
        if request.headers.get('X-Client') == 'mobile':
            body['access'] = data['access']  # native clients have no cookie jar
        response.data = body
        logger.info(f"{user.username} login via phone ({'new user' if created else 'existing'})")
        audit_session(user, 'LOGIN', request, {'method': 'phone', 'created': created})
        return response

    @staticmethod
    def _holders(User, mobile):
        # the last 8 digits (stored numbers may have spaces/dashes between them) narrow the candidates via the DB,
        # then compare the normalised numbers exactly
        tail = r'\D*'.join(mobile[-8:]) + r'\D*$'
        return [u for u in User.objects.filter(mobile_number__regex=tail).order_by('id')
                if normalize_mobile(u.mobile_number) == mobile]

    def _get_or_create_user(self, uid, mobile):
        User = get_user_model()

        with transaction.atomic():
            # a) Already linked
            social = (SocialAccount.objects.select_related('user')
                      .filter(provider='phone', provider_uid=uid).first())
            if social:
                if not social.user.is_active:
                    return None, False
                social.save(update_fields=['last_login_at'])
                return social.user, False

            # b) An account whose number was *proven* → link. A number somebody merely typed at signup proves
            #    nothing: whoever now passes the SMS check is the real owner, so the typed claim is withdrawn
            #    instead of handing them that account (it could belong to someone who pre-registered their number).
            holders = self._holders(User, mobile)
            user = next((u for u in holders if u.mobile_verified), None)
            for u in holders:
                if u is not user and not u.mobile_verified:
                    u.mobile_number = ''
                    u.save(update_fields=['mobile_number'])
            created = False

            # c) No account → create
            if user is None:
                user = create_user_with_defaults(
                    unique_username(User, '', fallback=f'user{mobile[-4:]}'), '',
                    mobile_number=mobile if len(mobile) <= 12 else '',
                )
                created = True

            if not user.is_active:
                return None, False

            if not user.mobile_verified:
                user.mobile_verified = True
                user.save(update_fields=['mobile_verified'])
            SocialAccount.objects.create(user=user, provider='phone', provider_uid=uid)
            return user, created
