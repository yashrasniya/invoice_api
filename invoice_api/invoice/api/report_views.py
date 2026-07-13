from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from invoice_api.permissions import HasMethodPermission
from invoice_api.scoping import user_scope_q
from django.db.models.functions import TruncDay, TruncWeek, TruncMonth
from django.db.models import Sum
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from invoice.models import Invoice

class CashFlowReportAPIView(APIView):
    permission_classes = [IsAuthenticated, HasMethodPermission]
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
    permission_classes = [IsAuthenticated, HasMethodPermission]
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
    permission_classes = [IsAuthenticated, HasMethodPermission]
    required_permissions_map = {'GET': 'report.view'}

    def get(self, request):
        start_date_str = request.query_params.get('start_date')
        end_date_str = request.query_params.get('end_date')

        if not start_date_str or not end_date_str:
            return Response({'error': 'start_date and end_date are required'}, status=400)

        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

        invoices = Invoice.objects.filter(
            user_scope_q(request),
            date__range=[start_date, end_date]
        )

        sales_invoices = invoices.filter(invoice_type='sales')
        purchase_invoices = invoices.filter(invoice_type='purchase')

        # Aggregate Sales
        sales_data = sales_invoices.aggregate(
            total_final=Sum('total_final_amount'),
            total_gst=Sum('gst_final_amount')
        )
        sales_total = sales_data['total_final'] or 0
        sales_gst = sales_data['total_gst'] or 0
        sales_taxable = float(sales_total) - float(sales_gst)

        # Aggregate Purchases
        purchases_data = purchase_invoices.aggregate(
            total_final=Sum('total_final_amount'),
            total_gst=Sum('gst_final_amount')
        )
        purchases_total = purchases_data['total_final'] or 0
        purchases_gst = purchases_data['total_gst'] or 0
        purchases_taxable = float(purchases_total) - float(purchases_gst)

        net_gst = float(sales_gst) - float(purchases_gst)

        return Response({
            'total_sales_taxable': float(sales_taxable),
            'total_purchases_taxable': float(purchases_taxable),
            'output_gst': float(sales_gst),
            'input_gst': float(purchases_gst),
            'net_gst_payable': float(net_gst)
        })
