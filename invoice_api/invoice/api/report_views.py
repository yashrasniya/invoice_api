from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from invoice_api.permissions import HasMethodPermission, HasFeature
from invoice_api.scoping import user_scope_q
from django.db.models.functions import TruncDay, TruncWeek, TruncMonth
from django.db.models import Sum
from datetime import datetime, timedelta
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
        
        # Recent purchases
        recent_purchases = purchase_invoices.order_by('-date')[:5]
        recent_data = []
        for inv in recent_purchases:
            recent_data.append({
                "id": inv.id,
                "invoice_number": inv.invoice_number,
                "date": inv.date.strftime('%Y-%m-%d') if inv.date else "",
                "amount": inv.total_final_amount,
                "vendor_name": inv.receiver.name if inv.receiver else "-"
            })

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
                                     note_totals, rupees, split_tax)

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

        sales_data = sales_invoices.aggregate(
            total_final=Sum('total_final_amount'), total_gst=Sum('gst_final_amount'))
        sales_total = sales_data['total_final'] or 0
        sales_gst = sales_data['total_gst'] or 0

        purchases_data = purchase_invoices.aggregate(
            total_final=Sum('total_final_amount'), total_gst=Sum('gst_final_amount'))
        purchases_total = purchases_data['total_final'] or 0
        purchases_gst = purchases_data['total_gst'] or 0

        company = getattr(request, 'company', None)
        home_state = getattr(company, 'state_code', None) if company else None
        split = split_tax(sales_invoices, home_state)

        notes = note_totals(CreditDebitNote.objects.filter(scope),
                            start_date, end_date)

        # data-quality checks look wider than the period: a purchase with no
        # GST recorded is worth flagging whenever it happened
        issues = data_quality(
            company,
            Invoice.objects.filter(scope, invoice_type='sales'),
            Invoice.objects.filter(scope, invoice_type='purchase'),
            split)

        return Response({
            'period': period,
            'period_label': label,
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),

            # headline figures, in whole rupees as returns are filed
            'total_sales_taxable': rupees(float(sales_total) - float(sales_gst)),
            'total_purchases_taxable': rupees(float(purchases_total) - float(purchases_gst)),
            'output_gst': rupees(sales_gst),
            'input_gst': rupees(purchases_gst),
            'net_gst_payable': rupees(float(sales_gst) - float(purchases_gst)),

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
            # the notes carry no tax component in the data model, so they are
            # reported alongside the liability rather than netted into it
            'notes_reduce_liability': False,

            # rate-wise (GSTR-1 table 12) needs per-line tax that the invoice
            # line items don't reliably carry — see `rate_breakdown_available`
            'rate_breakdown_available': False,

            'data_quality': issues,
        })
