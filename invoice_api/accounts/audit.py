"""
Session audit helper: records LOGIN / LOGOUT / LOGIN_FAILED events in the
AuditLog. Called explicitly from the auth views (SimpleJWT does not fire
Django's user_logged_in/out signals, and the tenant middleware's
current_user_ctx is not yet set during login).
"""
import logging

logger = logging.getLogger(__name__)


def client_ip(request):
    xff = request.META.get('HTTP_X_FORWARDED_FOR')
    if xff:
        return xff.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def audit_session(user, action, request, extra=None):
    """action: 'LOGIN' | 'LOGOUT' | 'LOGIN_FAILED'. Never raises."""
    try:
        from accounts.models import AuditLog
        data = {
            'ip': client_ip(request),
            'user_agent': request.META.get('HTTP_USER_AGENT', '')[:200],
        }
        if extra:
            data.update(extra)
        AuditLog.objects.create(
            company=getattr(user, 'user_company', None),
            user=user if getattr(user, 'pk', None) else None,
            action=action,
            resource_type='SESSION',
            resource_id=str(getattr(user, 'pk', '') or ''),
            new_data=data,
        )
    except Exception:
        logger.exception("session audit write failed")
