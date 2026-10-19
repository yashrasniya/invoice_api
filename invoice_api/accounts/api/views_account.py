from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts import deletion


class DeleteAccountView(APIView):
    """The signed-in person asks to delete their account. The account is locked straight away and an admin is
    emailed; the data is removed by an admin, or automatically after deletion.PURGE_AFTER_DAYS."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if user.is_superuser:
            return Response({'error': 'Administrator accounts cannot be deleted here.'}, status=status.HTTP_403_FORBIDDEN)
        if request.data.get('confirm') != 'DELETE':
            return Response({'error': 'Send confirm: "DELETE" to delete your account.'}, status=status.HTTP_400_BAD_REQUEST)
        # accounts that sign in with a password prove it; Google-only accounts have none to check
        if user.has_usable_password() and not user.check_password(request.data.get('password') or ''):
            return Response({'error': 'Password is wrong.'}, status=status.HTTP_400_BAD_REQUEST)
        deletion.request_deletion(user)
        return Response({'detail': 'Your account has been deleted. Your data will be removed permanently within '
                                   f'{deletion.PURGE_AFTER_DAYS} days.'})
