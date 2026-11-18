"""E-way bill endpoints (Phase A: details + bulk-upload JSON, no portal API).

    GET  /api/eway/<invoice_id>/      details, "needed?" verdict, issues
    PUT  /api/eway/<invoice_id>/      save details / the EWB number from the portal
    GET  /api/eway/json/?ids=1,2      issues per invoice; &download=1 for the file
    GET  /api/eway/pending/?days=30   sales invoices that need one and don't have it

Rules and the file format: invoice/eway.py.
"""
import json
from datetime import timedelta

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import AuditLog
from invoice import eway
from invoice.models import EwayBill, Invoice
from invoice_api.gst import is_valid_state_code
from invoice_api.permissions import HasFeature, HasMethodPermission
from invoice_api.scoping import user_scope_q

MAX_BULK = 50
_PREFETCH = ('products__product_properties__new_product_in_frontend',)


class EwayBillSerializer(serializers.ModelSerializer):
    # typed with spaces as the portal prints it ("3310 0123 4567"); cleaned below
    ewb_number = serializers.CharField(required=False, allow_blank=True, max_length=20)
    vehicle_number = serializers.CharField(required=False, allow_blank=True, max_length=20)
    transporter_id = serializers.CharField(required=False, allow_blank=True, max_length=20)

    class Meta:
        model = EwayBill
        fields = ('sub_supply_type', 'doc_type',
                  'ship_to_name', 'ship_to_address', 'ship_to_place', 'ship_to_state_code',
                  'ship_to_pincode', 'distance_km',
                  'transport_mode', 'vehicle_number', 'vehicle_type', 'transporter_id',
                  'transporter_name', 'transport_doc_number', 'transport_doc_date',
                  'ewb_number', 'ewb_date', 'valid_until', 'status', 'source', 'updated_at')
        read_only_fields = ('source', 'updated_at')

    def validate_vehicle_number(self, value):
        value = eway.normalize_vehicle(value)
        err = eway.vehicle_error(value)
        if err:
            raise serializers.ValidationError(err)
        return value

    def validate_transporter_id(self, value):
        value = (value or '').replace(' ', '').upper()
        err = eway.transporter_id_error(value)
        if err:
            raise serializers.ValidationError(err)
        return value

    def validate_ship_to_pincode(self, value):
        value = (value or '').strip()
        if value and not eway.PIN_RE.match(value):
            raise serializers.ValidationError('A PIN code is 6 digits.')
        return value

    def validate_ship_to_state_code(self, value):
        if value is not None and (not is_valid_state_code(value) or value == 96):
            raise serializers.ValidationError('Pick an Indian state.')
        return value

    def validate_distance_km(self, value):
        if value > eway.MAX_DISTANCE_KM:
            raise serializers.ValidationError(f'At most {eway.MAX_DISTANCE_KM} km.')
        return value

    def validate_ewb_number(self, value):
        value = (value or '').replace(' ', '')
        if value and not eway.EWB_NUMBER_RE.match(value):
            raise serializers.ValidationError('An e-way bill number is 12 digits.')
        return value

    def validate(self, attrs):
        inst = self.instance
        number = attrs.get('ewb_number', getattr(inst, 'ewb_number', ''))
        status = attrs.get('status', getattr(inst, 'status', 'draft'))
        if status == 'generated' and not number:
            raise serializers.ValidationError({'ewb_number': 'Enter the e-way bill number from the portal.'})
        if status == 'cancelled' and not number:
            raise serializers.ValidationError({'status': 'Only a generated e-way bill can be cancelled.'})
        if number and status == 'draft':
            attrs['status'] = 'generated'
        if not number:
            attrs['status'] = 'draft'
            attrs['ewb_date'] = attrs['valid_until'] = None
        elif attrs.get('status', status) == 'generated':
            generated = attrs.get('ewb_date') or getattr(inst, 'ewb_date', None) or timezone.now()
            attrs['ewb_date'] = generated
            if not attrs.get('valid_until'):
                attrs['valid_until'] = eway.validity_until(
                    generated,
                    attrs.get('distance_km', getattr(inst, 'distance_km', 0)),
                    attrs.get('vehicle_type', getattr(inst, 'vehicle_type', 'R')))
        return attrs


def _invoice(request, invoice_id):
    return (Invoice.objects.filter(user_scope_q(request), id=invoice_id)
            .select_related('receiver', 'eway_bill').prefetch_related(*_PREFETCH).first())


def _payload(request, invoice):
    company = getattr(request, 'company', None)
    saved = eway.getattr_safe(invoice, 'eway_bill')
    ewb = saved or eway.default_for(invoice)
    bill = eway.Bill(invoice, company, ewb)
    preview = eway.validity_until(timezone.now(), ewb.distance_km, ewb.vehicle_type)
    return {
        'invoice': {'id': invoice.id, 'invoice_number': invoice.invoice_number,
                    'date': invoice.date, 'customer': getattr(invoice.receiver, 'name', None),
                    'total': eway.money(invoice.total_final_amount)},
        'verdict': bill.verdict,
        'saved': saved is not None,
        'eway_bill': EwayBillSerializer(ewb).data,
        'ready': not bill.has_errors,
        'issues': bill.issues,
        # what "valid until" would be for one generated now with this distance
        'validity_if_generated_now': preview,
    }


class EwayBillDetailView(APIView):
    permission_classes = [IsAuthenticated, HasMethodPermission, HasFeature.with_code('eway_bill')]
    required_permissions_map = {'GET': 'invoice.view', 'PUT': 'invoice.update'}

    def get(self, request, invoice_id):
        invoice = _invoice(request, invoice_id)
        if invoice is None:
            return Response({'error': 'Invoice not found.'}, status=404)
        return Response(_payload(request, invoice))

    def put(self, request, invoice_id):
        invoice = _invoice(request, invoice_id)
        if invoice is None:
            return Response({'error': 'Invoice not found.'}, status=404)
        if invoice.invoice_type != 'sales':
            return Response({'error': 'E-way bills here are for sales invoices only.'}, status=400)
        saved = eway.getattr_safe(invoice, 'eway_bill')
        before = EwayBillSerializer(saved).data if saved else None
        ser = EwayBillSerializer(saved or eway.default_for(invoice), data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        obj = ser.save(invoice=invoice, updated_by=request.user)
        invoice.eway_bill = obj
        after = EwayBillSerializer(obj).data
        AuditLog.objects.create(
            company=getattr(request, 'company', None), user=request.user,
            action='UPDATE' if saved else 'CREATE', resource_type='EWAY_BILL',
            resource_id=str(invoice.id), previous_data=_jsonable(before), new_data=_jsonable(after))
        return Response(_payload(request, invoice))


def _jsonable(data):
    return json.loads(json.dumps(data, default=str)) if data is not None else None


class EwayBillJsonView(APIView):
    """Issues for a set of invoices, or (download=1) the bulk-upload file.

    The file is refused (409, with the issues) while any invoice has an
    error, as with GSTR-1: a file with guessed data is never produced.
    """
    permission_classes = [IsAuthenticated, HasMethodPermission, HasFeature.with_code('eway_bill')]
    required_permissions_map = {'GET': 'invoice.view'}

    def get(self, request):
        try:
            ids = [int(x) for x in str(request.query_params.get('ids', '')).split(',') if x.strip()]
        except ValueError:
            return Response({'error': 'ids must be invoice ids separated by commas.'}, status=400)
        if not ids:
            return Response({'error': 'Pick at least one invoice.'}, status=400)
        if len(ids) > MAX_BULK:
            return Response({'error': f'At most {MAX_BULK} invoices per file.'}, status=400)
        invoices = list(Invoice.objects.filter(user_scope_q(request), id__in=ids)
                        .select_related('receiver', 'eway_bill').prefetch_related(*_PREFETCH)
                        .order_by('date', 'id'))
        company = getattr(request, 'company', None)
        bills = [eway.Bill(inv, company) for inv in invoices]
        report = [{'invoice_id': b.invoice.id, 'invoice_number': b.invoice.invoice_number,
                   'ready': not b.has_errors, 'verdict': b.verdict, 'issues': b.issues} for b in bills]
        missing = sorted(set(ids) - {inv.id for inv in invoices})

        if request.query_params.get('download') in ('1', 'true'):
            if missing or any(b.has_errors for b in bills):
                return Response({'error': 'Fix the errors before downloading the e-way bill file.',
                                 'bills': report, 'not_found': missing}, status=409)
            body = json.dumps(eway.bulk_json(b.entry for b in bills), indent=2)
            resp = HttpResponse(body, content_type='application/json')
            stamp = timezone.localtime().strftime('%Y%m%d_%H%M')
            resp['Content-Disposition'] = f'attachment; filename="EWB_bulk_{stamp}.json"'
            return resp
        return Response({'bills': report, 'not_found': missing,
                         'ready': not missing and all(r['ready'] for r in report)})


class EwayBillPendingView(APIView):
    """Recent sales invoices whose goods need an e-way bill and that have
    none generated. A reminder list: nothing here blocks anything."""
    permission_classes = [IsAuthenticated, HasMethodPermission, HasFeature.with_code('eway_bill')]
    required_permissions_map = {'GET': 'invoice.view'}

    def get(self, request):
        try:
            days = min(max(int(request.query_params.get('days', 30)), 1), eway.MAX_DOC_AGE_DAYS)
        except ValueError:
            days = 30
        since = timezone.localdate() - timedelta(days=days)
        qs = (Invoice.objects.filter(user_scope_q(request), invoice_type='sales', date__gte=since)
              .exclude(eway_bill__status__in=('generated',))
              .select_related('receiver').prefetch_related(*_PREFETCH).order_by('-date', '-id'))
        company = getattr(request, 'company', None)
        rows = []
        for inv in qs:
            v = eway.verdict(inv, company)
            if v['needed']:
                rows.append({'invoice_id': inv.id, 'invoice_number': inv.invoice_number, 'date': inv.date,
                             'customer': getattr(inv.receiver, 'name', None),
                             'consignment_value': v['consignment_value']})
        return Response({'days': days, 'count': len(rows), 'invoices': rows})
