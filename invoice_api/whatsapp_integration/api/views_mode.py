"""
Company WhatsApp sending mode.

    GET  /api/whatsapp/mode/   current mode + available options & limits
    POST /api/whatsapp/mode/   {"mode": "own"|"platform"}  (whatsapp.manage)
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from invoice_api.limits import get_limit
from invoice_api.permissions import HasMethodPermission

from accounts.models import AuditLog

from ..models import (CompanyWhatsAppSettings, PlatformWhatsAppAccount,
                      WhatsAppIntegration)
from ..resolver import (OWN_DEFAULT_LIMIT, OWN_FEATURE, PLATFORM_FEATURE,
                        get_company_mode)


class WhatsAppModeAPIView(APIView):
    permission_classes = [IsAuthenticated, HasMethodPermission]
    required_permissions_map = {'POST': 'whatsapp.manage'}

    def get(self, request):
        company = request.company
        if company is None:
            return Response({'error': 'No company.'}, status=400)
        features = request.features or set()
        account = PlatformWhatsAppAccount.get_active()
        own_configured = WhatsAppIntegration.objects.filter(
            status='active', user__user_company=company).exists()

        own_limit = get_limit(request, OWN_FEATURE, 'sends_per_day')
        platform_limit = get_limit(request, PLATFORM_FEATURE, 'sends_per_day')
        if platform_limit is None and account:
            platform_limit = account.default_daily_limit

        settings_obj = CompanyWhatsAppSettings.objects.filter(
            company=company).select_related('default_invoice_template').first()
        default_template = None
        if settings_obj and settings_obj.default_invoice_template:
            default_template = {
                'id': settings_obj.default_invoice_template.id,
                'template_name': settings_obj.default_invoice_template.template_name,
            }

        return Response({
            'mode': get_company_mode(company),
            'default_invoice_template': default_template,
            'options': {
                'platform': {
                    'available': PLATFORM_FEATURE in features and bool(
                        account and account.phone_number_id),
                    'in_plan': PLATFORM_FEATURE in features,
                    'configured': bool(account and account.phone_number_id),
                    'sends_per_day': platform_limit,
                },
                'own': {
                    'available': OWN_FEATURE in features,
                    'in_plan': OWN_FEATURE in features,
                    'configured': own_configured,
                    'sends_per_day': (OWN_DEFAULT_LIMIT if own_limit is None
                                      else own_limit),
                },
            },
        })

    def post(self, request):
        company = request.company
        if company is None:
            return Response({'error': 'No company.'}, status=400)

        defaults = {'updated_by': request.user}

        # optional: change the sending mode
        if 'mode' in request.data:
            mode = request.data.get('mode')
            if mode not in ('own', 'platform'):
                return Response({'error': "mode must be 'own' or 'platform'."},
                                status=400)
            features = request.features or set()
            required = OWN_FEATURE if mode == 'own' else PLATFORM_FEATURE
            if required not in features:
                return Response(
                    {'detail': "Your plan does not include this option.",
                     'code': 'upgrade_required'},
                    status=status.HTTP_403_FORBIDDEN)
            defaults['mode'] = mode
        else:
            defaults['mode'] = get_company_mode(company)

        # optional: set/clear the default invoice template for sends
        if 'default_invoice_template' in request.data:
            template_id = request.data.get('default_invoice_template')
            if template_id in (None, '', 0):
                defaults['default_invoice_template'] = None
            else:
                from yaml_manager.models import Yaml
                template = Yaml.objects.filter(
                    id=template_id, company=company).first()
                if template is None:
                    return Response(
                        {'error': 'Template not found in your company.'},
                        status=400)
                defaults['default_invoice_template'] = template

        obj, _ = CompanyWhatsAppSettings.objects.update_or_create(
            company=company, defaults=defaults)
        AuditLog.objects.create(
            company=company, user=request.user, action='UPDATE',
            resource_type='WHATSAPP_MODE', resource_id=str(obj.id),
            new_data={'mode': obj.mode,
                      'default_invoice_template':
                          obj.default_invoice_template_id})
        return Response({
            'mode': obj.mode,
            'default_invoice_template': (
                {'id': obj.default_invoice_template.id,
                 'template_name': obj.default_invoice_template.template_name}
                if obj.default_invoice_template else None),
        })
