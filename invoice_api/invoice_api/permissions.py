"""
DRF permission classes & function-view decorators for feature gating and
tenant permissions.

`upgrade_required` (403) is distinguishable from plain `permission_denied`
so the frontend can render an upgrade CTA.
"""
from functools import wraps

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission


class UpgradeRequired(PermissionDenied):
    default_code = 'upgrade_required'  # frontend renders upgrade CTA


def require_feature(feature_code):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if feature_code not in (getattr(request, 'features', None) or set()):
                raise UpgradeRequired(f"Feature '{feature_code}' is not in your plan.")
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


def has_permission(permission_code):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if permission_code not in (getattr(request, 'permissions', None) or set()):
                raise PermissionDenied(f"Missing permission: '{permission_code}'.")
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


class HasFeature(BasePermission):
    feature_code = None
    message = 'Your plan does not include this feature.'
    code = 'upgrade_required'

    @classmethod
    def with_code(cls, code):
        return type('HasFeature', (cls,), {'feature_code': code})

    def has_permission(self, request, view):
        code = self.feature_code or getattr(view, 'required_feature', None)
        if not code:
            return True
        return code in (getattr(request, 'features', None) or set())


class HasPermission(BasePermission):
    permission_code = None

    @classmethod
    def with_code(cls, code):
        return type('HasPermission', (cls,), {'permission_code': code})

    def has_permission(self, request, view):
        code = self.permission_code or getattr(view, 'required_permission', None)
        if not code:
            return True
        return code in (getattr(request, 'permissions', None) or set())


class HasMethodPermission(BasePermission):
    """Per-HTTP-method permission codes, e.g. on the view:

        required_permissions_map = {'GET': 'invoice.view',
                                    'POST': 'invoice.create'}

    Methods missing from the map are allowed through.
    """

    def has_permission(self, request, view):
        perm_map = getattr(view, 'required_permissions_map', {})
        code = perm_map.get(request.method)
        if not code:
            return True
        return code in (getattr(request, 'permissions', None) or set())


class HasMethodFeature(BasePermission):
    """Per-HTTP-method plan-feature codes, e.g. on the view:

        required_features_map = {'POST': 'template_designer'}

    Methods missing from the map are allowed through. Failures surface as
    403 upgrade_required.
    """
    message = 'Your plan does not include this feature.'
    code = 'upgrade_required'

    def has_permission(self, request, view):
        feat_map = getattr(view, 'required_features_map', {})
        code = feat_map.get(request.method)
        if not code:
            return True
        return code in (getattr(request, 'features', None) or set())


class HasRole(BasePermission):
    role_name = None

    @classmethod
    def with_name(cls, name):
        return type('HasRole', (cls,), {'role_name': name})

    def has_permission(self, request, view):
        name = self.role_name or getattr(view, 'required_role', None)
        if not name or not request.user or not request.user.is_authenticated:
            return False
        company = getattr(request, 'company', None)
        if not company:
            return False
        # direct roles OR roles via groups
        return (request.user.roles.filter(company=company, name=name).exists() or
                request.user.company_groups.filter(company=company, roles__name=name).exists())


class HasAnyPermission(BasePermission):
    permission_codes = []

    @classmethod
    def with_codes(cls, *codes):
        return type('HasAnyPermission', (cls,), {'permission_codes': list(codes)})

    def has_permission(self, request, view):
        codes = self.permission_codes or getattr(view, 'required_permissions_any', [])
        if not codes:
            return True
        user_perms = getattr(request, 'permissions', None) or set()
        return any(c in user_perms for c in codes)


class HasAllPermissions(BasePermission):
    permission_codes = []

    @classmethod
    def with_codes(cls, *codes):
        return type('HasAllPermissions', (cls,), {'permission_codes': list(codes)})

    def has_permission(self, request, view):
        codes = self.permission_codes or getattr(view, 'required_permissions_all', [])
        if not codes:
            return True
        user_perms = getattr(request, 'permissions', None) or set()
        return all(c in user_perms for c in codes)


class IsTenantAdmin(BasePermission):
    message = 'Tenant admin access required.'

    def has_permission(self, request, view):
        return 'role.manage' in (getattr(request, 'permissions', None) or set())


class IsProductOwner(BasePermission):
    message = 'Product owner access required.'

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and (
            u.is_superuser or
            u.roles.filter(company__isnull=True, name='Product Owner').exists()))
