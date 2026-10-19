"""
Per-company invoice header field settings.

    GET  /api/invoice-header-config/    current settings + the field catalog
    POST /api/invoice-header-config/    save settings (template.manage)

Anyone who can open the bill editor may read the settings (it needs them to
decide what to show); only template managers may change them. Validation
lives in invoice.header_config so the rules are the same wherever they run.
"""
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import AuditLog
from invoice_api.permissions import HasMethodPermission

from .. import header_config
from ..models import InvoiceHeaderConfig


def settings_for(company):
    """The stored settings map for a company, or None when never configured."""
    if not company:
        return None
    row = InvoiceHeaderConfig.objects.filter(company=company).first()
    return row.fields if row else None


def _features(request, company):
    """Company-level feature switches managed on the same settings screen.

    `available` is what the plan allows; `enabled` is the company's own
    opt-in. Both must hold for the feature to appear in the editor.
    """
    return {
        'line_item_images': {
            'available': 'line_item_images' in (getattr(request, 'features', None) or set()),
            'enabled': bool(company.enable_line_item_images),
        },
    }


def _payload(stored, request, company):
    return {
        'fields': header_config.normalize(stored),
        'catalog': header_config.CATALOG,
        'features': _features(request, company),
    }


class InvoiceHeaderConfigAPIView(APIView):
    permission_classes = [IsAuthenticated, HasMethodPermission]
    required_permissions_map = {'POST': 'template.manage'}

    def get(self, request):
        company = getattr(request, 'company', None)
        if not company:
            return Response({'error': 'No company.'}, status=400)
        # Read must not create a row; an untouched company stays unconfigured.
        return Response(_payload(settings_for(company), request, company))

    def post(self, request):
        company = getattr(request, 'company', None)
        if not company:
            return Response({'error': 'No company.'}, status=400)

        incoming = request.data.get('fields')
        features = request.data.get('features')

        # Validate everything before writing anything.
        merged = None
        if incoming is not None:
            try:
                merged = header_config.validate(settings_for(company), incoming)
            except ValueError as exc:
                return Response({'error': str(exc)}, status=400)

        want_images = None
        if isinstance(features, dict) and 'line_item_images' in features:
            want_images = header_config._truthy(features['line_item_images'])
            available = _features(request, company)['line_item_images']['available']
            # Switching it off is always allowed; switching it on needs the plan.
            if want_images and not available:
                return Response({'error': "Your plan doesn't include line item images."},
                                status=400)

        if merged is not None:
            obj, _ = InvoiceHeaderConfig.objects.update_or_create(
                company=company, defaults={'fields': merged, 'updated_by': request.user})
            AuditLog.objects.create(
                company=company, user=request.user, action='UPDATE',
                resource_type='INVOICE_HEADER_CONFIG', resource_id=str(obj.id),
                new_data={'fields': merged})

        if want_images is not None and want_images != company.enable_line_item_images:
            company.enable_line_item_images = want_images
            company.save(update_fields=['enable_line_item_images'])
            AuditLog.objects.create(
                company=company, user=request.user, action='UPDATE',
                resource_type='COMPANY_FEATURES', resource_id=str(company.id),
                new_data={'line_item_images': want_images})

        return Response(_payload(settings_for(company), request, company))
