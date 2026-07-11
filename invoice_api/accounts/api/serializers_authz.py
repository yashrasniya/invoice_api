"""
Serializers for the Tenant Admin authz APIs.

Guards enforced here:
- escalation guard: a Tenant Admin can only grant permissions they hold
- all referenced objects must belong to request.company
- system roles/permissions are read-only to tenants
- last Company Admin cannot be removed (lockout prevention)
"""
from rest_framework import serializers

from accounts.authz_seed import COMPANY_ADMIN_ROLE
from accounts.models import (AuditLog, CompanyGroup, CompanyPermission,
                             CompanyRole, User, UserDirectPermission)


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyPermission
        fields = ['id', 'name', 'code', 'description', 'permission_type',
                  'is_system_permission', 'company']
        read_only_fields = ['is_system_permission', 'company']


class UserLiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email', 'is_company_admin']


class _TenantScopedMixin:
    @property
    def _request(self):
        return self.context['request']

    @property
    def _company(self):
        return self._request.company

    @property
    def _requester_perms(self):
        return set(self._request.permissions or set())

    def _validate_permission_ids(self, permissions):
        """Permissions must be visible to the tenant AND held by the requester."""
        for perm in permissions:
            if perm.company_id is not None and perm.company_id != self._company.id:
                raise serializers.ValidationError(
                    f"Permission '{perm.code}' does not belong to your company.")
            if perm.code not in self._requester_perms:
                raise serializers.ValidationError(
                    f"You cannot grant a permission you do not hold: '{perm.code}'.")
        return permissions

    def _validate_company_users(self, users):
        for user in users:
            if user.user_company_id != self._company.id:
                raise serializers.ValidationError(
                    f"User '{user.username}' does not belong to your company.")
        return users


class RoleSerializer(_TenantScopedMixin, serializers.ModelSerializer):
    permissions = serializers.PrimaryKeyRelatedField(
        queryset=CompanyPermission.objects.all(), many=True, required=False)
    users = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), many=True, required=False)
    permission_codes = serializers.SerializerMethodField()
    user_names = serializers.SerializerMethodField()

    class Meta:
        model = CompanyRole
        fields = ['id', 'name', 'description', 'is_system_role',
                  'permissions', 'users', 'permission_codes', 'user_names']
        read_only_fields = ['is_system_role']

    def get_permission_codes(self, obj):
        return list(obj.permissions.values_list('code', flat=True))

    def get_user_names(self, obj):
        return [{'id': u.id, 'username': u.username} for u in obj.users.all()]

    def validate_permissions(self, permissions):
        return self._validate_permission_ids(permissions)

    def validate_users(self, users):
        return self._validate_company_users(users)

    def validate(self, attrs):
        # tenants cannot edit system roles
        if self.instance and self.instance.is_system_role:
            mutable = set(attrs.keys()) - {'users'}   # membership of system roles is allowed
            if mutable:
                raise serializers.ValidationError(
                    "System roles are read-only (only user assignment is allowed).")
        return attrs

    def create(self, validated_data):
        validated_data['company'] = self._company
        validated_data['is_system_role'] = False
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # lockout prevention: don't allow removing the last Company Admin
        if instance.is_system_role and instance.name == COMPANY_ADMIN_ROLE and 'users' in validated_data:
            if len(validated_data['users']) == 0:
                raise serializers.ValidationError(
                    "A company must keep at least one Company Admin.")
        validated_data.pop('company', None)
        return super().update(instance, validated_data)


class GroupSerializer(_TenantScopedMixin, serializers.ModelSerializer):
    users = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), many=True, required=False)
    roles = serializers.PrimaryKeyRelatedField(
        queryset=CompanyRole.objects.all(), many=True, required=False)
    permissions = serializers.PrimaryKeyRelatedField(
        queryset=CompanyPermission.objects.all(), many=True, required=False)

    class Meta:
        model = CompanyGroup
        fields = ['id', 'name', 'description', 'users', 'roles', 'permissions']

    def validate_permissions(self, permissions):
        return self._validate_permission_ids(permissions)

    def validate_users(self, users):
        return self._validate_company_users(users)

    def validate_roles(self, roles):
        for role in roles:
            if role.company_id != self._company.id:
                raise serializers.ValidationError(
                    f"Role '{role.name}' does not belong to your company.")
            # escalation guard: adding a role to a group grants its permissions
            for code in role.permissions.values_list('code', flat=True):
                if code not in self._requester_perms:
                    raise serializers.ValidationError(
                        f"Role '{role.name}' contains a permission you do not hold: '{code}'.")
        return roles

    def create(self, validated_data):
        validated_data['company'] = self._company
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop('company', None)
        return super().update(instance, validated_data)


class DirectPermissionSerializer(_TenantScopedMixin, serializers.ModelSerializer):
    permission_code = serializers.CharField(source='permission.code', read_only=True)

    class Meta:
        model = UserDirectPermission
        fields = ['id', 'user', 'permission', 'permission_code', 'is_granted', 'granted_by']
        read_only_fields = ['granted_by']

    def validate_user(self, user):
        self._validate_company_users([user])
        return user

    def validate_permission(self, permission):
        self._validate_permission_ids([permission])
        return permission

    def create(self, validated_data):
        validated_data['company'] = self._company
        validated_data['granted_by'] = self._request.user
        # upsert on (user, permission, company)
        obj, _ = UserDirectPermission.objects.update_or_create(
            user=validated_data['user'],
            permission=validated_data['permission'],
            company=self._company,
            defaults={'is_granted': validated_data.get('is_granted', True),
                      'granted_by': self._request.user})
        return obj


class AuditLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.username', read_only=True, default=None)

    class Meta:
        model = AuditLog
        fields = ['id', 'user', 'user_name', 'action', 'resource_type',
                  'resource_id', 'previous_data', 'new_data', 'timestamp']
