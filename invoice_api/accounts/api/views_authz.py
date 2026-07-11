"""
Tenant Admin management APIs (all guarded by IsTenantAdmin, tenant-scoped).

    /api/authz/roles/                     GET POST
    /api/authz/roles/{id}/                GET PUT PATCH DELETE
    /api/authz/roles/{id}/users/          POST          (assign user)
    /api/authz/roles/{id}/users/{uid}/    DELETE        (unassign user)
    /api/authz/groups/                    GET POST
    /api/authz/groups/{id}/               GET PUT PATCH DELETE
    /api/authz/permissions/               GET           (catalog visible to tenant)
    /api/authz/users/                     GET           (company members)
    /api/authz/users/{id}/permissions/    GET POST      (direct grant/deny)
    /api/authz/users/{id}/permissions/{perm_id}/ DELETE (remove direct entry)
    /api/authz/users/{id}/effective-permissions/ GET
    /api/authz/audit-log/                 GET           (company-scoped, read-only)
    /api/authz/me/                        GET           (my perms/features/subscription)
"""
from django.db.models import Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from invoice_api.middleware import get_user_permissions
from invoice_api.permissions import IsTenantAdmin

from accounts.authz_seed import COMPANY_ADMIN_ROLE
from accounts.models import (AuditLog, CompanyGroup, CompanyPermission,
                             CompanyRole, User, UserDirectPermission)
from .serializers_authz import (AuditLogSerializer, DirectPermissionSerializer,
                                GroupSerializer, PermissionSerializer,
                                RoleSerializer, UserLiteSerializer)


class RoleViewSet(viewsets.ModelViewSet):
    serializer_class = RoleSerializer
    permission_classes = [IsAuthenticated, IsTenantAdmin]

    def get_queryset(self):
        return (CompanyRole.objects
                .filter(company=self.request.company)
                .prefetch_related('permissions', 'users')
                .order_by('id'))

    def perform_destroy(self, instance):
        if instance.is_system_role:
            raise PermissionDenied("System roles cannot be deleted.")
        instance.delete()

    @action(detail=True, methods=['post'], url_path='users')
    def assign_user(self, request, pk=None):
        role = self.get_object()
        user = self._get_company_user(request.data.get('user_id'))
        role.users.add(user)
        return Response({'status': 'assigned'}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['delete'],
            url_path='users/(?P<user_id>[0-9]+)')
    def unassign_user(self, request, pk=None, user_id=None):
        role = self.get_object()
        user = self._get_company_user(user_id)
        # lockout prevention
        if (role.is_system_role and role.name == COMPANY_ADMIN_ROLE
                and role.users.count() <= 1 and role.users.filter(pk=user.pk).exists()):
            raise ValidationError("A company must keep at least one Company Admin.")
        role.users.remove(user)
        return Response({'status': 'unassigned'}, status=status.HTTP_200_OK)

    def _get_company_user(self, user_id):
        try:
            return User.objects.get(pk=user_id, user_company=self.request.company)
        except (User.DoesNotExist, ValueError, TypeError):
            raise ValidationError("User not found in your company.")


class GroupViewSet(viewsets.ModelViewSet):
    serializer_class = GroupSerializer
    permission_classes = [IsAuthenticated, IsTenantAdmin]

    def get_queryset(self):
        return (CompanyGroup.objects
                .filter(company=self.request.company)
                .prefetch_related('users', 'roles', 'permissions')
                .order_by('id'))


class PermissionCatalogView(ListAPIView):
    """Permission catalog visible to the tenant: system + own custom."""
    serializer_class = PermissionSerializer
    permission_classes = [IsAuthenticated, IsTenantAdmin]
    pagination_class = None

    def get_queryset(self):
        return (CompanyPermission.objects
                .filter(Q(company__isnull=True) | Q(company=self.request.company))
                .order_by('code'))


class CompanyUsersView(ListAPIView):
    serializer_class = UserLiteSerializer
    permission_classes = [IsAuthenticated, IsTenantAdmin]
    pagination_class = None

    def get_queryset(self):
        return User.objects.filter(user_company=self.request.company).order_by('username')


class UserDirectPermissionView(APIView):
    permission_classes = [IsAuthenticated, IsTenantAdmin]

    def _get_user(self, request, user_id):
        try:
            return User.objects.get(pk=user_id, user_company=request.company)
        except User.DoesNotExist:
            raise ValidationError("User not found in your company.")

    def get(self, request, user_id):
        user = self._get_user(request, user_id)
        entries = UserDirectPermission.objects.filter(
            user=user, company=request.company).select_related('permission')
        return Response(DirectPermissionSerializer(
            entries, many=True, context={'request': request}).data)

    def post(self, request, user_id):
        user = self._get_user(request, user_id)
        data = dict(request.data)
        data['user'] = user.id
        serializer = DirectPermissionSerializer(data=data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def delete(self, request, user_id, perm_id=None):
        user = self._get_user(request, user_id)
        deleted, _ = UserDirectPermission.objects.filter(
            user=user, company=request.company, permission_id=perm_id).delete()
        if not deleted:
            return Response({'detail': 'No such direct permission.'},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(status=status.HTTP_204_NO_CONTENT)


class EffectivePermissionsView(APIView):
    """Debugging/UI helper: a user's resolved permission set."""
    permission_classes = [IsAuthenticated, IsTenantAdmin]

    def get(self, request, user_id):
        try:
            user = User.objects.get(pk=user_id, user_company=request.company)
        except User.DoesNotExist:
            raise ValidationError("User not found in your company.")
        # bypass cache for accuracy in the admin UI
        perms = get_user_permissions(user, request.company, use_cache=False)
        return Response({
            'user': user.id,
            'username': user.username,
            'permissions': sorted(perms),
            'roles': list(user.roles.filter(company=request.company)
                          .values_list('name', flat=True)),
            'groups': list(user.company_groups.filter(company=request.company)
                           .values_list('name', flat=True)),
        })


class CompanyAuditLogView(ListAPIView):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated, IsTenantAdmin]

    def get_queryset(self):
        qs = AuditLog.objects.filter(company=self.request.company)
        resource_type = self.request.query_params.get('resource_type')
        if resource_type:
            qs = qs.filter(resource_type=resource_type)
        return qs.select_related('user').order_by('-timestamp')[:500]


class MyAccessView(APIView):
    """Current user's tenant context: permissions, features, subscription.
    Used by the frontend to gate menus/buttons."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        sub = request.subscription
        return Response({
            'company_id': request.company.id if request.company else None,
            'company_name': request.company.company_name if request.company else None,
            'permissions': sorted(request.permissions or set()),
            'features': sorted(request.features or set()),
            'subscription': dict(sub) if sub else None,
            'is_tenant_admin': 'role.manage' in (request.permissions or set()),
            'is_product_owner': bool(request.user.is_superuser or
                                     request.user.roles.filter(
                                         company__isnull=True,
                                         name='Product Owner').exists()),
        })
