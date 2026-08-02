from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.authentication import JWTAuthentication
from django.conf import settings

from rest_framework.authentication import CSRFCheck, BaseAuthentication
from rest_framework import exceptions

from accounts.models import ServiceToken


def enforce_csrf(request):
    check = CSRFCheck(request)
    check.process_request(request)
    reason = check.process_view(request, None, (), {})
    if reason:
        raise exceptions.PermissionDenied('CSRF Failed: %s' % reason)

class CustomAuthentication(JWTAuthentication):
    def authenticate(self, request):
        header = self.get_header(request)

        if header is None:
            raw_token = request.COOKIES.get(settings.SIMPLE_JWT['AUTH_COOKIE']) or None
        else:
            raw_token = self.get_raw_token(header)
        if raw_token is None:
            return None

        validated_token = self.get_validated_token(raw_token)
        # enforce_csrf(request)
        
        token_id = validated_token.get('token_id')
        if token_id is not None:
            from adminconfig.models import AdminJWTToken
            try:
                db_token = AdminJWTToken.objects.get(id=token_id)
                if not db_token.is_active:
                    raise AuthenticationFailed("This token has been deactivated.")
            except AdminJWTToken.DoesNotExist:
                raise AuthenticationFailed("This token has been revoked.")

        return self.get_user(validated_token), validated_token

class ServiceTokenAuthentication(BaseAuthentication):

    def authenticate(self, request):

        auth_header = request.headers.get("Authorization")

        if not auth_header:
            return None

        try:
            prefix, token = auth_header.split(" ")

            if prefix.lower() != "bearer":
                raise AuthenticationFailed("Invalid token format")

        except ValueError:
            raise AuthenticationFailed("Invalid authorization header")

        service_token = ServiceToken.objects.filter(
            token=token,
            is_active=True
        ).select_related("user").first()

        if not service_token:
            raise AuthenticationFailed("Invalid token")
            
        from invoice_api.middleware import get_active_subscription, get_enabled_features
        company = getattr(service_token.user, 'user_company', None)
        if company:
            sub = get_active_subscription(company)
            features = get_enabled_features(sub)
            if 'api_access' not in features:
                raise AuthenticationFailed("Your plan does not include API access.")

        return (service_token.user, None)


class AdminJWTTokenAuthentication(JWTAuthentication):
    def authenticate(self, request):
        header = self.get_header(request)

        if header is None:
            raw_token = request.COOKIES.get(settings.SIMPLE_JWT['AUTH_COOKIE']) or None
        else:
            raw_token = self.get_raw_token(header)
        if raw_token is None:
            return None

        validated_token = self.get_validated_token(raw_token)

        token_id = validated_token.get('token_id')
        if token_id is None:
            raise AuthenticationFailed("This endpoint requires an admin-generated API token.")

        from adminconfig.models import AdminJWTToken
        try:
            db_token = AdminJWTToken.objects.get(id=token_id)
            if not db_token.is_active:
                raise AuthenticationFailed("This token has been deactivated.")
        except AdminJWTToken.DoesNotExist:
            raise AuthenticationFailed("This token has been revoked.")

        user = self.get_user(validated_token)

        # Check for X-User-Id or x-user-id header to impersonate/switch to that user context
        impersonated_user_val = request.headers.get("X-User-Id") or request.headers.get("x-user-id")
        if impersonated_user_val:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            try:
                if str(impersonated_user_val).isdigit():
                    selected_user = User.objects.get(id=int(impersonated_user_val))
                else:
                    selected_user = User.objects.get(username=impersonated_user_val)
                user = selected_user
            except User.DoesNotExist:
                raise AuthenticationFailed("The specified user in X-User-Id header does not exist.")

        return user, validated_token