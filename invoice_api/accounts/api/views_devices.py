from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import DeviceToken
from accounts.push import is_expo_token


class DeviceTokenView(APIView):
    """Register / unregister this phone for push notifications.

        POST   /api/devices/   {"token": "ExponentPushToken[...]", "platform": "ios"|"android"}
        DELETE /api/devices/   {"token": "..."}     (on sign-out)
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = (request.data.get('token') or '').strip()
        if not is_expo_token(token):
            return Response({'error': 'A valid Expo push token is required.'}, status=status.HTTP_400_BAD_REQUEST)
        platform = request.data.get('platform')
        platform = platform if platform in ('ios', 'android') else ''
        # the token belongs to the phone: if someone else signed in on it before, it moves to this user
        DeviceToken.objects.update_or_create(token=token, defaults={'user': request.user, 'platform': platform})
        return Response({'registered': True}, status=status.HTTP_201_CREATED)

    def delete(self, request):
        token = (request.data.get('token') or request.query_params.get('token') or '').strip()
        # scoped to the caller so one user cannot unregister another's phone
        DeviceToken.objects.filter(token=token, user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
