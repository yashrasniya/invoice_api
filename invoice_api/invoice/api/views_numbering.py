"""
Per-company invoice numbering settings.

    GET  /api/invoice-numbering/                      current settings + preview
    GET  /api/invoice-numbering/?template=...         dry-run preview, touches no row
    POST /api/invoice-numbering/                      save settings (template.manage)

The template grammar lives in invoice.numbering and is validated here, so the
UI can never preview something the server would later reject.
"""
from django.utils import timezone
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import AuditLog
from invoice_api.permissions import HasMethodPermission

from .. import numbering
from ..models import CompanyInvoiceNumbering


def _payload(cfg):
    """The settings shape shared by GET and POST responses."""
    template = cfg.template if cfg else numbering.DEFAULT_TEMPLATE
    reset_period = cfg.reset_period if cfg else numbering.RESET_NEVER
    next_number = cfg.next_number if cfg else 1

    data = {
        'enabled': cfg.enabled if cfg else False,
        'template': template,
        'reset_period': reset_period,
        'next_number': next_number,
        'period_key': cfg.period_key if cfg else '',
        'updated_at': cfg.updated_at if cfg else None,
        'updated_by': cfg.updated_by.username if (cfg and cfg.updated_by) else None,
        'max_length': numbering.MAX_RENDERED_LEN,
        'gst_recommended_max_length': numbering.GST_RECOMMENDED_MAX_LEN,
        'reset_options': [{'value': v, 'label': l} for v, l in numbering.RESET_CHOICES],
        'tokens': numbering.TOKEN_CATALOG,
        'default_template': numbering.DEFAULT_TEMPLATE,
    }
    data.update(numbering.preview(template, reset_period, next_number))
    return data


class InvoiceNumberingAPIView(APIView):
    permission_classes = [IsAuthenticated, HasMethodPermission]
    required_permissions_map = {'POST': 'template.manage'}

    def get(self, request):
        # Dry-run preview while the admin types. Deliberately answers 200 even
        # for an invalid template: a half-typed value is not a client error,
        # and a 4xx stream would trip the frontend's global toast interceptor.
        if 'template' in request.query_params:
            try:
                seq = int(request.query_params.get('next_number') or 1)
            except (TypeError, ValueError):
                seq = 1
            return Response(numbering.preview(
                request.query_params.get('template') or '',
                request.query_params.get('reset_period') or numbering.RESET_NEVER,
                max(seq, 1)))

        company = getattr(request, 'company', None)
        if not company:
            return Response({'error': 'No company.'}, status=400)
        # Read must not create a row — an untouched company stays unconfigured.
        cfg = CompanyInvoiceNumbering.objects.filter(company=company).first()
        return Response(_payload(cfg))

    def post(self, request):
        company = getattr(request, 'company', None)
        if not company:
            return Response({'error': 'No company.'}, status=400)

        cfg = CompanyInvoiceNumbering.objects.filter(company=company).first()

        # Merge over what is stored, so validating a partial POST still checks
        # the template and reset period as a pair.
        template = request.data.get(
            'template', cfg.template if cfg else numbering.DEFAULT_TEMPLATE)
        reset_period = request.data.get(
            'reset_period', cfg.reset_period if cfg else numbering.RESET_NEVER)
        template = (template or '').strip()

        valid_resets = [v for v, _ in numbering.RESET_CHOICES]
        if reset_period not in valid_resets:
            return Response({'error': 'Unknown reset period.'}, status=400)

        try:
            numbering.validate_template(template, reset_period)
        except ValueError as exc:
            return Response({'error': str(exc)}, status=400)

        defaults = {'template': template, 'reset_period': reset_period,
                    'updated_by': request.user}

        if 'enabled' in request.data:
            value = request.data.get('enabled')
            defaults['enabled'] = value if isinstance(value, bool) else \
                str(value).lower() in ('true', '1', 'yes', 'on')

        if 'next_number' in request.data:
            try:
                nxt = int(request.data.get('next_number'))
            except (TypeError, ValueError):
                return Response({'error': 'Next number must be a whole number.'},
                                status=400)
            if not 1 <= nxt <= 2147483647:
                return Response({'error': 'Next number must be between 1 and 2147483647.'},
                                status=400)
            defaults['next_number'] = nxt

        # Switching reset period re-keys to today's period so the generator
        # never compares two different key formats — but the counter keeps
        # running, so enabling a reset mid-series doesn't restart at 1.
        if cfg is None or cfg.reset_period != reset_period:
            defaults['period_key'] = numbering.period_key(
                reset_period, timezone.localdate())

        obj, _ = CompanyInvoiceNumbering.objects.update_or_create(
            company=company, defaults=defaults)
        AuditLog.objects.create(
            company=company, user=request.user, action='UPDATE',
            resource_type='INVOICE_NUMBERING', resource_id=str(obj.id),
            new_data={'enabled': obj.enabled, 'template': obj.template,
                      'reset_period': obj.reset_period,
                      'next_number': obj.next_number})
        return Response(_payload(obj))
