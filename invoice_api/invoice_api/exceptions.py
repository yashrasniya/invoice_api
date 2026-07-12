"""
Custom DRF exception handler: expose the machine-readable error code in the
response body (DRF's default JSON rendering drops ErrorDetail.code, so the
frontend couldn't distinguish `upgrade_required` from `permission_denied`).

    {"detail": "Plan limit reached.", "code": "upgrade_required"}
"""
from rest_framework.views import exception_handler


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None and isinstance(response.data, dict):
        detail = response.data.get('detail')
        code = getattr(detail, 'code', None)
        if code and 'code' not in response.data:
            response.data['code'] = code
    return response
