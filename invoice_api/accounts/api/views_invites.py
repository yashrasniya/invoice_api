"""
User invite system.

Tenant Admin (requires `user.invite` permission):
    GET  /api/authz/invites/                  list company invites
    POST /api/authz/invites/                  {email, role?} → create + send mail
    POST /api/authz/invites/{id}/resend/      re-send the mail
    DELETE /api/authz/invites/{id}/           revoke a pending invite

Public (no auth):
    GET  /api/invites/<token>/                invite info for the accept page
    POST /api/invites/<token>/accept/         {username, password, first_name?,
                                               last_name?} → create user, join
                                               company, assign role, log in
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.middleware import csrf
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from invoice_api.limits import enforce_limit
from invoice_api.permissions import BasePermission

from accounts.audit import audit_session, client_ip
from accounts.authz_seed import MEMBER_ROLE, ensure_company_roles
from accounts.models import (AuditLog, CompanyPermission, CompanyRole, User,
                             UserInvite)

logger = logging.getLogger(__name__)


class CanInviteUsers(BasePermission):
    message = 'You need the user.invite permission.'

    def has_permission(self, request, view):
        return 'user.invite' in (getattr(request, 'permissions', None) or set())


class InviteSerializer(serializers.ModelSerializer):
    role_name = serializers.CharField(source='role.name', read_only=True, default=None)
    invited_by_name = serializers.CharField(source='invited_by.username', read_only=True, default=None)
    invite_link = serializers.SerializerMethodField()

    class Meta:
        model = UserInvite
        fields = ['id', 'email', 'role', 'role_name', 'status', 'invited_by_name',
                  'created_at', 'expires_at', 'invite_link']
        read_only_fields = ['status', 'created_at', 'expires_at']

    def get_invite_link(self, obj):
        # only expose the link to tenant admins (this serializer is admin-facing)
        return f"{settings.FRONTEND_URL}/invite/{obj.token}" if obj.status == 'pending' else None


def _send_invite_mail(invite):
    """Send the invite email. Returns True on success; never raises."""
    link = f"{settings.FRONTEND_URL}/invite/{invite.token}"
    company = invite.company.company_name or "a company"
    inviter = invite.invited_by.name() if invite.invited_by else "An administrator"
    subject = f"You've been invited to join {company}"
    message = (
        f"Hi,\n\n"
        f"{inviter} has invited you to join {company} on Invoice Orvine.\n\n"
        f"Accept the invitation and create your account here:\n{link}\n\n"
        f"This link expires on {invite.expires_at.strftime('%d %b %Y')}.\n\n"
        f"If you weren't expecting this invitation you can ignore this email."
    )
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [invite.email],
                  fail_silently=False)
        return True
    except Exception:
        logger.exception("invite mail to %s failed", invite.email)
        return False


class InviteListCreateView(APIView):
    permission_classes = [IsAuthenticated, CanInviteUsers]

    def get(self, request):
        invites = (UserInvite.objects
                   .filter(company=request.company)
                   .select_related('role', 'invited_by')
                   .order_by('-created_at'))
        # opportunistically mark expired ones
        now = timezone.now()
        for inv in invites:
            if inv.status == 'pending' and inv.expires_at < now:
                UserInvite.objects.filter(pk=inv.pk).update(status='expired')
                inv.status = 'expired'
        return Response(InviteSerializer(invites, many=True).data)

    def post(self, request):
        email = (request.data.get('email') or '').strip().lower()
        if not email:
            raise ValidationError({'email': 'Email is required.'})
        serializers.EmailField().run_validation(email)

        # already a member somewhere?
        existing = User.objects.filter(email__iexact=email).first()
        if existing and existing.user_company_id == request.company.id:
            raise ValidationError({'email': 'This user is already in your company.'})
        if existing and existing.user_company_id:
            raise ValidationError({'email': 'This email already belongs to another company.'})

        # plan limit on users (counts members + open invites)
        current = (User.objects.filter(user_company=request.company).count() +
                   UserInvite.objects.filter(company=request.company,
                                             status='pending').count())
        enforce_limit(request, 'invoicing', 'users', current)

        # optional role, must belong to this company
        role = None
        role_id = request.data.get('role')
        if role_id:
            role = CompanyRole.objects.filter(
                pk=role_id, company=request.company).first()
            if role is None:
                raise ValidationError({'role': 'Role not found in your company.'})

        if UserInvite.objects.filter(company=request.company, email=email,
                                     status='pending').exists():
            raise ValidationError({'email': 'There is already a pending invite for this email.'})

        invite = UserInvite.objects.create(
            company=request.company, email=email, role=role,
            invited_by=request.user)
        mail_sent = _send_invite_mail(invite)

        AuditLog.objects.create(
            company=request.company, user=request.user, action='INVITE',
            resource_type='INVITE', resource_id=str(invite.id),
            new_data={'email': email, 'role': role.name if role else MEMBER_ROLE,
                      'mail_sent': mail_sent})

        data = InviteSerializer(invite).data
        data['mail_sent'] = mail_sent
        return Response(data, status=status.HTTP_201_CREATED)


class InviteDetailView(APIView):
    permission_classes = [IsAuthenticated, CanInviteUsers]

    def _get_invite(self, request, invite_id):
        invite = UserInvite.objects.filter(
            pk=invite_id, company=request.company).first()
        if invite is None:
            raise ValidationError('Invite not found.')
        return invite

    def delete(self, request, invite_id):
        invite = self._get_invite(request, invite_id)
        if invite.status != 'pending':
            raise ValidationError('Only pending invites can be revoked.')
        invite.status = 'revoked'
        invite.save(update_fields=['status'])
        AuditLog.objects.create(
            company=request.company, user=request.user, action='REVOKE',
            resource_type='INVITE', resource_id=str(invite.id),
            new_data={'email': invite.email})
        return Response(status=status.HTTP_204_NO_CONTENT)


class InviteResendView(APIView):
    permission_classes = [IsAuthenticated, CanInviteUsers]

    def post(self, request, invite_id):
        invite = UserInvite.objects.filter(
            pk=invite_id, company=request.company).first()
        if invite is None or not invite.is_valid():
            raise ValidationError('No valid pending invite to resend.')
        mail_sent = _send_invite_mail(invite)
        return Response({'mail_sent': mail_sent})


# ---------------------------------------------------------------------------
# Public accept endpoints
# ---------------------------------------------------------------------------

class InviteInfoView(APIView):
    """Info for the accept page. No auth."""
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, token):
        invite = UserInvite.objects.filter(token=token).select_related('company').first()
        if invite is None or not invite.is_valid():
            return Response({'valid': False}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            'valid': True,
            'email': invite.email,
            'company_name': invite.company.company_name,
            'expires_at': invite.expires_at,
            'existing_account': User.objects.filter(
                email__iexact=invite.email).exists(),
        })


class InviteAcceptView(APIView):
    """Accept an invite: create (or attach) the user, assign role, log in."""
    permission_classes = [AllowAny]
    authentication_classes = []

    @transaction.atomic
    def post(self, request, token):
        invite = (UserInvite.objects.select_for_update()
                  .filter(token=token).select_related('company', 'role').first())
        if invite is None or not invite.is_valid():
            raise PermissionDenied('This invitation is invalid or has expired.')

        user = User.objects.filter(email__iexact=invite.email).first()
        if user and user.user_company_id:
            raise ValidationError('This account already belongs to a company.')

        if user is None:
            username = (request.data.get('username') or '').strip()
            password = request.data.get('password') or ''
            if not username or not password:
                raise ValidationError('username and password are required.')
            if User.objects.filter(username=username).exists():
                raise ValidationError({'username': 'This username is taken.'})
            if len(password) < 8:
                raise ValidationError({'password': 'Password must be at least 8 characters.'})
            user = User.objects.create_user(
                username=username, email=invite.email, password=password)
            user.first_name = (request.data.get('first_name') or '')[:150]
            user.last_name = (request.data.get('last_name') or '')[:150]

        # join the company as a regular member
        user.user_company = invite.company
        user.is_company_admin = False
        user.is_active = True
        user.save()

        # assign role (invited role or default Member system role)
        _, member_role = ensure_company_roles(
            CompanyRole, CompanyPermission, invite.company)
        (invite.role or member_role).users.add(user)

        invite.status = 'accepted'
        invite.accepted_user = user
        invite.accepted_at = timezone.now()
        invite.save(update_fields=['status', 'accepted_user', 'accepted_at'])

        AuditLog.objects.create(
            company=invite.company, user=user, action='ACCEPT',
            resource_type='INVITE', resource_id=str(invite.id),
            new_data={'email': invite.email, 'ip': client_ip(request)})

        # log them straight in (same cookie flow as Login)
        from .views import get_tokens_for_user, user_detail
        response = Response()
        data = get_tokens_for_user(user)
        response.set_cookie(
            key=settings.SIMPLE_JWT['AUTH_COOKIE'],
            value=data['access'],
            expires=settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'],
            secure=settings.SIMPLE_JWT['AUTH_COOKIE_SECURE'],
            httponly=settings.SIMPLE_JWT['AUTH_COOKIE_HTTP_ONLY'],
            samesite=settings.SIMPLE_JWT['AUTH_COOKIE_SAMESITE'],
        )
        csrf.get_token(request)
        response.data = user_detail(user).data
        audit_session(user, 'LOGIN', request, {'method': 'invite_accept'})
        return response
