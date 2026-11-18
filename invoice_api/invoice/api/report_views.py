from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from invoice_api.permissions import HasMethodPermission, HasFeature
from invoice_api.scoping import user_scope_q
from django.db.models.functions import TruncDay, TruncWeek, TruncMonth
from django.db.models import F, Sum
from datetime import datetime, timedelta
from decimal import Decimal
from django.db.models import DecimalField, Q, Value
from django.db.models.functions import Coalesce

ZERO_D = Value(Decimal('0'), output_field=DecimalField(max_digits=20, decimal_places=2))
from dateutil.relativedelta import relativedelta
from invoice.models import Invoice

class CashFlowReportAPIView(APIView):
    permission_classes = [IsAuthenticated, HasMethodPermission, HasFeature.with_code('advanced_reports')]
    required_permissions_map = {'GET': 'report.view'}

    def get(self, request):
        start_date_str = request.query_params.get('start_date')
        end_date_str = request.query_params.get('end_date')
        interval = request.query_params.get('interval', 'daily')

        # Default date range if not provided: last 30 days
        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        else:
            end_date = datetime.now().date()

        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        else:
            start_date = end_date - timedelta(days=30)

        queryset = Invoice.objects.filter(
            user_scope_q(request),
            date__gte=start_date,
            date__lte=end_date
        )

        if interval == 'weekly':
            trunc_func = TruncWeek('date')
        elif interval == 'monthly':
            trunc_func = TruncMonth('date')
        else:
            trunc_func = TruncDay('date')

        aggregated = queryset.annotate(
            period=trunc_func
        ).values('period', 'invoice_type').annotate(
            total_amount=Sum('total_final_amount')
        ).order_by('period')

        # Convert queryset result to a dictionary mapping period -> {inflow, outflow}
        data_map = {}
        for item in aggregated:
            if item['period']:
                period = item['period']
                if isinstance(period, datetime):
                    period_date = period.date()
                elif isinstance(period, str):
                    period_date = datetime.strptime(period[:10], '%Y-%m-%d').date()
                else:
                    period_date = period
                    
                if period_date not in data_map:
                    data_map[period_date] = {'inflow': 0, 'outflow': 0}
                    
                amount = item['total_amount'] or 0
                if item.get('invoice_type') == 'purchase':
                    data_map[period_date]['outflow'] += amount
                else:
                    data_map[period_date]['inflow'] += amount

        # Generate continuous intervals
        response_data = []
        current_date = start_date

        if interval == 'monthly':
            # align current_date to start of month
            current_date = current_date.replace(day=1)
            end_date_aligned = end_date.replace(day=1)
            while current_date <= end_date_aligned:
                period_data = data_map.get(current_date, {'inflow': 0, 'outflow': 0})
                inflow = period_data['inflow']
                outflow = period_data['outflow']
                response_data.append({
                    "date": current_date.strftime('%Y-%m-%d'),
                    "inflow": float(inflow),
                    "outflow": float(outflow),
                    "net": float(inflow) - float(outflow)
                })
                current_date += relativedelta(months=1)
        elif interval == 'weekly':
            # align current_date to start of week (Monday)
            current_date = current_date - timedelta(days=current_date.weekday())
            end_date_aligned = end_date - timedelta(days=end_date.weekday())
            while current_date <= end_date_aligned:
                period_data = data_map.get(current_date, {'inflow': 0, 'outflow': 0})
                inflow = period_data['inflow']
                outflow = period_data['outflow']
                response_data.append({
                    "date": current_date.strftime('%Y-%m-%d'),
                    "inflow": float(inflow),
                    "outflow": float(outflow),
                    "net": float(inflow) - float(outflow)
                })
                current_date += timedelta(weeks=1)
        else:
            while current_date <= end_date:
                period_data = data_map.get(current_date, {'inflow': 0, 'outflow': 0})
                inflow = period_data['inflow']
                outflow = period_data['outflow']
                response_data.append({
                    "date": current_date.strftime('%Y-%m-%d'),
                    "inflow": float(inflow),
                    "outflow": float(outflow),
                    "net": float(inflow) - float(outflow)
                })
                current_date += timedelta(days=1)

        return Response(response_data)


class PurchaseInvoiceSummaryAPIView(APIView):
    permission_classes = [IsAuthenticated, HasMethodPermission, HasFeature.with_code('purchases_invoice')]
    required_permissions_map = {'GET': 'invoice.view'}

    def get(self, request):
        today = datetime.now().date()
        start_of_month = today.replace(day=1)
        
        purchase_invoices = Invoice.objects.filter(
            user_scope_q(request),
            invoice_type='purchase'
        )
        
        # This month purchases
        this_month_purchases = purchase_invoices.filter(date__gte=start_of_month)
        
        total_purchases_amount = purchase_invoices.aggregate(Sum('total_final_amount'))['total_final_amount__sum'] or 0
        total_purchases_gst = purchase_invoices.aggregate(Sum('gst_final_amount'))['gst_final_amount__sum'] or 0
        
        this_month_purchases_amount = this_month_purchases.aggregate(Sum('total_final_amount'))['total_final_amount__sum'] or 0
        
        total_count = purchase_invoices.count()
        this_month_count = this_month_purchases.count()
        
        # Recent purchases (newest first, undated last, same tiebreak as the list)
        recent_purchases = purchase_invoices.select_related('vendor', 'receiver').order_by(
            F('date').desc(nulls_last=True), '-id')[:8]
        recent_data = []
        for inv in recent_purchases:
            recent_data.append({
                "id": inv.id,
                "invoice_number": inv.invoice_number,
                "date": inv.date.strftime('%Y-%m-%d') if inv.date else "",
                "amount": inv.total_final_amount,
                "vendor_name": (inv.vendor or inv.receiver).name if (inv.vendor or inv.receiver) else "-",
                # what add_balance_fields reads, so each row can show what is still owed
                "total_final_amount": inv.total_final_amount,
                "payment_status": inv.payment_status,
                "invoice_type": "purchase",
            })
        from .views import add_balance_fields
        add_balance_fields(recent_data)

        return Response({
            "total_purchases_amount": float(total_purchases_amount),
            "total_purchases_gst": float(total_purchases_gst),
            "this_month_purchases_amount": float(this_month_purchases_amount),
            "total_count": total_count,
            "this_month_count": this_month_count,
            "recent_purchases": recent_data
        })

class GSTSummaryAPIView(APIView):
    permission_classes = [IsAuthenticated, HasMethodPermission, HasFeature.with_code('advanced_reports')]
    required_permissions_map = {'GET': 'report.view'}

    #: filing periods. A rolling window is deliberately not offered — it can
    #: coincidentally equal a real period and then silently drift the next day.
    PERIODS = ('this_month', 'last_month', 'this_quarter', 'last_quarter', 'this_fy')

    def get(self, request):
        from invoice.models import CreditDebitNote
        from invoice_api.gst import (data_quality, gst_period_bounds,
                                     note_totals, off_slab_rates, rupees,
                                     split_tax)

        period = request.query_params.get('period')
        start_date_str = request.query_params.get('start_date')
        end_date_str = request.query_params.get('end_date')

        if period in self.PERIODS:
            start_date, end_date, label = gst_period_bounds(period)
        elif start_date_str or end_date_str:
            if not (start_date_str and end_date_str):
                return Response(
                    {'error': 'Both start_date and end_date are required.'},
                    status=400)
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            except ValueError:
                # previously an uncaught ValueError → 500
                return Response(
                    {'error': 'Dates must be in YYYY-MM-DD format.'}, status=400)
            if end_date < start_date:
                return Response(
                    {'error': 'end_date cannot be before start_date.'}, status=400)
            period, label = 'custom', f'{start_date} to {end_date}'
        else:
            # default to the current filing month, not a rolling 30 days
            period = 'this_month'
            start_date, end_date, label = gst_period_bounds(period)

        scope = user_scope_q(request)
        in_period = Invoice.objects.filter(scope, date__range=[start_date, end_date])
        sales_invoices = in_period.filter(invoice_type='sales')
        purchase_invoices = in_period.filter(invoice_type='purchase')

        # Reverse charge: the *recipient* pays the GST. An RCM sale adds nothing
        # to our output tax; an RCM purchase is tax we must pay (in cash) and
        # can then claim as input credit. On an RCM invoice the stored total
        # excludes the GST, so taxable = total there (see gst.taxable_value).
        rcm = Q(reverse_charge=True)
        tsum = lambda q: Coalesce(Sum('total_final_amount', filter=q), ZERO_D)
        gsum = lambda q: Coalesce(Sum('gst_final_amount', filter=q), ZERO_D)

        sales_data = sales_invoices.aggregate(
            total=tsum(~rcm), gst=gsum(~rcm), rcm_total=tsum(rcm), rcm_gst=gsum(rcm))
        sales_gst = sales_data['gst']
        sales_taxable = sales_data['total'] - sales_data['gst'] + sales_data['rcm_total']
        rcm_sales_gst = sales_data['rcm_gst']

        purchases_data = purchase_invoices.aggregate(
            total=tsum(~rcm), gst=gsum(~rcm), rcm_total=tsum(rcm), rcm_gst=gsum(rcm))
        rcm_payable = purchases_data['rcm_gst']
        purchases_gst = purchases_data['gst'] + rcm_payable       # RCM tax is claimable credit too
        purchases_taxable = purchases_data['total'] - purchases_data['gst'] + purchases_data['rcm_total']

        company = getattr(request, 'company', None)
        home_state = getattr(company, 'state_code', None) if company else None
        split = split_tax(sales_invoices.filter(reverse_charge=False), home_state)

        notes = note_totals(CreditDebitNote.objects.filter(scope),
                            start_date, end_date)

        # data-quality checks look wider than the period: a purchase with no
        # GST recorded is worth flagging whenever it happened
        issues = data_quality(
            company,
            Invoice.objects.filter(scope, invoice_type='sales'),
            Invoice.objects.filter(scope, invoice_type='purchase'),
            split, notes=notes,
            off_slab=off_slab_rates(Invoice.objects.filter(scope, invoice_type='sales')))
        out_adj = notes.pop('output_tax_adjustment')
        in_adj = notes.pop('input_tax_adjustment')
        # output liability includes the tax we owe on RCM purchases
        output_tax = Decimal(sales_gst) + out_adj + rcm_payable
        input_tax = Decimal(purchases_gst) + in_adj

        return Response({
            'period': period,
            'period_label': label,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),

            # headline figures, in whole rupees as returns are filed
            'total_sales_taxable': rupees(sales_taxable),
            'total_purchases_taxable': rupees(purchases_taxable),
            # reverse charge: payable by us in cash on RCM purchases (counted in
            # net_gst_payable and as input credit); RCM sales' tax is the buyer's
            'rcm_payable': rupees(rcm_payable),
            'rcm_sales_tax': rupees(rcm_sales_gst),
            'output_gst': rupees(sales_gst),
            'input_gst': rupees(purchases_gst),
            # after credit/debit notes that carry a GST amount
            'output_tax_adjustment': rupees(out_adj),
            'input_tax_adjustment': rupees(in_adj),
            'net_gst_payable': rupees(output_tax - input_tax),

            'sales_invoice_count': sales_invoices.count(),
            'purchase_invoice_count': purchase_invoices.count(),

            'tax_split': {
                'cgst': rupees(split['cgst']),
                'sgst': rupees(split['sgst']),
                'igst': rupees(split['igst']),
                'unclassified': rupees(split['unclassified']),
                'intra_taxable': rupees(split['intra_taxable']),
                'inter_taxable': rupees(split['inter_taxable']),
                'unclassified_taxable': rupees(split['unclassified_taxable']),
                'unclassified_invoices': split['unclassified_invoices'],
            },

            **notes,
            # True when every note in the period had its GST netted in above;
            # otherwise `notes_without_gst` of them were left out
            'notes_reduce_liability': notes['notes_without_gst'] == 0,

            # rate-wise (GSTR-1 table 12) needs per-line tax that the invoice
            # line items don't reliably carry — see `rate_breakdown_available`
            'rate_breakdown_available': False,

            'data_quality': issues,
        })


def _sales_scope(request, start, end):
    """Sales, cancelled sales, FY numbers and outward notes for a range."""
    from datetime import date as _date
    from invoice.models import CreditDebitNote

    scope = user_scope_q(request)
    sales = Invoice.objects.filter(scope, invoice_type='sales', date__range=[start, end])
    deleted = Invoice.all_objects.filter(scope, invoice_type='sales', is_deleted=True, date__range=[start, end])
    fy_start = _date(start.year if start.month >= 4 else start.year - 1, 4, 1)
    fy_numbers = Invoice.objects.filter(
        scope, invoice_type='sales', date__range=[fy_start, _date(fy_start.year + 1, 3, 31)]
    ).values_list('invoice_number', 'id')
    # outward-supply notes only: vendor notes belong to the purchase side
    notes = (CreditDebitNote.objects.filter(scope, date__range=[start, end], vendor__isnull=True)
             .exclude(Q(invoice__isnull=False) & Q(invoice__invoice_type='purchase')))
    return sales, deleted, fy_numbers, notes


def _build_gstr1(request, start, end, mode='gstr1', skip_b2b_until=None):
    from invoice_api.gstr1 import Gstr1
    sales, deleted, fy_numbers, notes = _sales_scope(request, start, end)
    return Gstr1(getattr(request, 'company', None), sales, notes, start, end, deleted_sales_qs=deleted,
                 fy_numbers=fy_numbers, mode=mode, skip_b2b_until=skip_b2b_until)


def _build_gstr3b(request, gstr1, start, end):
    from invoice.models import CreditDebitNote
    from invoice_api.gstr3b import Gstr3b
    scope = user_scope_q(request)
    purchases = Invoice.objects.filter(scope, invoice_type='purchase', date__range=[start, end])
    vendor_notes = CreditDebitNote.objects.filter(scope, date__range=[start, end]).filter(
        Q(vendor__isnull=False) | Q(invoice__invoice_type='purchase'))
    return Gstr3b(getattr(request, 'company', None), gstr1, purchases, vendor_notes)


def _quarter_months(start):
    """For the month starting `start`: (end of its quarter's second month,
    whether it is the quarter's third month). FY quarters are Apr-Jun,
    Jul-Sep, Oct-Dec and Jan-Mar, so they line up with calendar quarters."""
    import calendar
    from datetime import date as _date
    position = (start.month - 1) % 3
    m2 = start.month - position + 1
    return _date(start.year, m2, calendar.monthrange(start.year, m2)[1]), position == 2


class GSTR1APIView(APIView):
    """GSTR-1 for a filing period.

    GET → summary of each table plus the issues to fix before filing.
    GET ?download=1 → the portal / offline-tool JSON, refused (409, with the
    issues) while any error-level issue remains, so a file with guessed or
    missing data is never produced.

    Periods are a month or an Indian FY quarter; `fp` in the file is the
    period's last month. For a quarterly (QRMP) filer a month in the quarter's
    first two months is the IFF (B2B only), the third month alone is refused,
    and the quarter leaves out the B2B already sent in those IFFs unless
    ?include_iff=1.
    """
    permission_classes = [IsAuthenticated, HasMethodPermission, HasFeature.with_code('advanced_reports')]
    required_permissions_map = {'GET': 'report.view'}
    PERIODS = ('this_month', 'last_month', 'this_quarter', 'last_quarter')
    IFF_LIMIT = Decimal('5000000')          # ₹50 lakh of B2B value per month

    def get(self, request):
        import json
        from django.http import HttpResponse
        from invoice_api.gst import gst_period_bounds

        period = request.query_params.get('period', 'last_month')
        if period not in self.PERIODS:
            return Response({'error': f"period must be one of {', '.join(self.PERIODS)}."}, status=400)
        start, end, label = gst_period_bounds(period)
        company = getattr(request, 'company', None)
        quarterly = getattr(company, 'gst_filing_frequency', 'monthly') == 'quarterly'
        is_month = period.endswith('_month')

        mode, skip_until, return_type = 'gstr1', None, 'GSTR-1'
        include_iff = request.query_params.get('include_iff') in ('1', 'true')
        if quarterly and is_month:
            m2_end, third = _quarter_months(start)
            if third:
                return Response({'error': f'You file GSTR-1 quarterly. {label} is the last month of its '
                                          'quarter, so its invoices go in the quarterly return: pick the quarter.',
                                 'code': 'quarterly_third_month'}, status=400)
            mode, return_type = 'iff', 'IFF'
        elif quarterly and not include_iff:
            skip_until, _ = _quarter_months(start)
            skip_until = skip_until if skip_until < end else None
        ret = _build_gstr1(request, start, end, mode=mode, skip_b2b_until=skip_until)

        if mode == 'iff':
            b2b_value = sum((Decimal(str(r['val'])) for invs in ret.b2b.values() for r in invs), Decimal('0'))
            if b2b_value > self.IFF_LIMIT:
                ret._issue('warning', 'iff_limit',
                           'The IFF takes up to ₹50 lakh of B2B invoices a month; upload the rest with the '
                           'quarterly GSTR-1.')

        if request.query_params.get('download'):
            if ret.has_errors:
                return Response({'error': f'Fix the errors before downloading the {return_type} file.',
                                 'issues': ret.issues}, status=409)
            body = json.dumps(ret.portal_json(), indent=2)
            resp = HttpResponse(body, content_type='application/json')
            fp = f'{end.month:02d}{end.year}'
            resp['Content-Disposition'] = (f'attachment; filename="{return_type.replace("-", "")}_'
                                           f'{ret.gstin or "NA"}_{fp}.json"')
            return resp

        errors = sum(1 for i in ret.issues if i['level'] == 'error')
        return Response({
            'period': period, 'period_label': label,
            'start_date': start.isoformat(), 'end_date': end.isoformat(),
            'gstin': ret.gstin, 'fp': f'{end.month:02d}{end.year}',
            'filing_frequency': 'quarterly' if quarterly else 'monthly',
            'return_type': return_type,
            # quarter of a quarterly filer: B2B of the first two months left out (sent in the IFF)
            'iff_months_left_out': bool(skip_until),
            **ret.summary(),
            'issues': ret.issues,
            'error_count': errors,
            'warning_count': len(ret.issues) - errors,
            'ready_to_file': errors == 0,
        })


class GSTR3BAPIView(APIView):
    """GSTR-3B figures for a period (month, or quarter for QRMP filers): what to
    type into the portal. A report: nothing is filed or downloaded."""
    permission_classes = [IsAuthenticated, HasMethodPermission, HasFeature.with_code('advanced_reports')]
    required_permissions_map = {'GET': 'report.view'}
    PERIODS = GSTR1APIView.PERIODS

    def get(self, request):
        from invoice_api.gst import gst_period_bounds

        period = request.query_params.get('period', 'last_month')
        if period not in self.PERIODS:
            return Response({'error': f"period must be one of {', '.join(self.PERIODS)}."}, status=400)
        start, end, label = gst_period_bounds(period)
        company = getattr(request, 'company', None)
        gstr1 = _build_gstr1(request, start, end)
        ret = _build_gstr3b(request, gstr1, start, end)
        issues = ret.issues
        quarterly = getattr(company, 'gst_filing_frequency', 'monthly') == 'quarterly'
        if quarterly and period.endswith('_month'):
            issues = issues + [{'level': 'warning', 'code': 'quarterly_filer', 'ref': None,
                                'message': 'You file GSTR-3B quarterly; pick the quarter for the return. '
                                           'This month is shown for reference (e.g. a PMT-06 payment).'}]
        errors = sum(1 for i in issues if i['level'] == 'error')
        return Response({
            'period': period, 'period_label': label,
            'start_date': start.isoformat(), 'end_date': end.isoformat(),
            'gstin': gstr1.gstin,
            'filing_frequency': 'quarterly' if quarterly else 'monthly',
            **ret.summary(),
            'issues': issues,
            'error_count': errors,
            'warning_count': len(issues) - errors,
        })


class GSTR9APIView(APIView):
    """GSTR-9 (annual return) figures for a financial year, from the books.
    ?fy=2025 is FY 2025-26; default is the last complete FY."""
    permission_classes = [IsAuthenticated, HasMethodPermission, HasFeature.with_code('advanced_reports')]
    required_permissions_map = {'GET': 'report.view'}

    def get(self, request):
        from datetime import date as _date
        from invoice_api.gstr3b import gstr9

        today = _date.today()
        current = today.year if today.month >= 4 else today.year - 1
        raw = request.query_params.get('fy')
        try:
            fy = int(raw) if raw else current - 1
        except ValueError:
            return Response({'error': 'fy must be the year the financial year starts, e.g. 2025.'}, status=400)
        if not 2017 <= fy <= current:
            return Response({'error': f'fy must be between 2017 and {current}.'}, status=400)
        start, end = _date(fy, 4, 1), _date(fy + 1, 3, 31)
        g1 = _build_gstr1(request, start, end)
        g3 = _build_gstr3b(request, g1, start, end)
        issues = list(g3.issues)
        if fy == current:
            issues.append({'level': 'warning', 'code': 'fy_in_progress', 'ref': None,
                           'message': 'This financial year is not over: the figures are so far.'})
        errors = sum(1 for i in issues if i['level'] == 'error')
        return Response({
            'fy': fy, 'fy_label': f'FY {fy}-{str(fy + 1)[2:]}',
            'start_date': start.isoformat(), 'end_date': end.isoformat(),
            'gstin': g1.gstin,
            **gstr9(g1, g3),
            'sales_counted': g1.counted, 'sales_left_out': g1.skipped, 'sales_with_errors': g1.flagged,
            'issues': issues,
            'error_count': errors,
            'warning_count': len(issues) - errors,
        })
