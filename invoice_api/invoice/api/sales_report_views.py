from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Sum, Count, Q
from django.db.models.functions import TruncDay, TruncWeek, TruncMonth
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

from invoice_api.permissions import HasMethodPermission, HasFeature
from invoice_api.scoping import user_scope_q
from invoice.models import Invoice, CreditDebitNote

class SalesReportAPIView(APIView):
    permission_classes = [IsAuthenticated, HasMethodPermission, HasFeature.with_code('advanced_reports')]
    required_permissions_map = {'GET': 'report.view'}

    def get(self, request):
        start_date_str = request.query_params.get('start_date')
        end_date_str = request.query_params.get('end_date')
        payment_status = request.query_params.get('payment_status')
        payment_method = request.query_params.get('payment_method')
        customer_id = request.query_params.get('customer')

        # Default date range if not provided: last 30 days
        if end_date_str:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        else:
            end_date = datetime.now().date()

        if start_date_str:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        else:
            start_date = end_date - timedelta(days=30)

        # Base queryset for sales invoices within scope and date range
        base_qs = Invoice.objects.filter(
            user_scope_q(request),
            invoice_type='sales',
            date__gte=start_date,
            date__lte=end_date
        )

        # Apply additional filters if present
        if payment_status:
            status_list = payment_status.split(',')
            base_qs = base_qs.filter(payment_status__in=status_list)
        if payment_method:
            method_list = payment_method.split(',')
            base_qs = base_qs.filter(payment_method__in=method_list)
        if customer_id:
            base_qs = base_qs.filter(receiver_id=customer_id)

        # --- Summary Cards ---
        total_sales_agg = base_qs.aggregate(
            total=Sum('total_final_amount'),
            gst=Sum('gst_final_amount')
        )
        total_sales = float(total_sales_agg['total'] or 0)
        gst_collected = float(total_sales_agg['gst'] or 0)
        total_invoices = base_qs.count()
        average_invoice_value = total_sales / total_invoices if total_invoices > 0 else 0

        paid_amount = float(base_qs.filter(payment_status='paid').aggregate(Sum('total_final_amount'))['total_final_amount__sum'] or 0)
        unpaid_amount = float(base_qs.filter(payment_status__in=['unpaid', 'partially_paid']).aggregate(Sum('total_final_amount'))['total_final_amount__sum'] or 0)
        overdue_amount = float(base_qs.filter(payment_status='overdue').aggregate(Sum('total_final_amount'))['total_final_amount__sum'] or 0)

        # Credit Notes
        credit_notes = CreditDebitNote.objects.filter(
            user_scope_q(request),
            note_type='credit',
            date__gte=start_date,
            date__lte=end_date
        )
        credit_notes_issued = credit_notes.count()
        credit_notes_amount = float(credit_notes.aggregate(Sum('amount'))['amount__sum'] or 0)

        # Discounts Given - Needs product level extraction if available in the model
        # As per the model, discount is not a direct field, so we approximate to 0 for now unless there's a custom field/property
        discount_given = 0.0

        # Top Customer (overall)
        top_customer_data = base_qs.exclude(receiver__isnull=True).values('receiver__name').annotate(total=Sum('total_final_amount')).order_by('-total').first()
        top_customer = top_customer_data['receiver__name'] if top_customer_data else "N/A"

        # Highest Sale Day
        highest_sale_day_data = base_qs.values('date').annotate(total=Sum('total_final_amount')).order_by('-total').first()
        highest_sale_day = highest_sale_day_data['date'].strftime('%Y-%m-%d') if highest_sale_day_data else "N/A"

        # Sales Growth (comparing to previous equivalent period)
        period_length = (end_date - start_date).days + 1
        prev_end_date = start_date - timedelta(days=1)
        prev_start_date = prev_end_date - timedelta(days=period_length - 1)
        
        prev_qs = Invoice.objects.filter(
            user_scope_q(request),
            invoice_type='sales',
            date__gte=prev_start_date,
            date__lte=prev_end_date
        )
        
        if payment_status:
            prev_qs = prev_qs.filter(payment_status__in=payment_status.split(','))
        if payment_method:
            prev_qs = prev_qs.filter(payment_method__in=payment_method.split(','))
        if customer_id:
            prev_qs = prev_qs.filter(receiver_id=customer_id)

        prev_total = float(prev_qs.aggregate(Sum('total_final_amount'))['total_final_amount__sum'] or 0)
        
        if prev_total > 0:
            sales_growth_pct = ((total_sales - prev_total) / prev_total) * 100
        else:
            sales_growth_pct = 100.0 if total_sales > 0 else 0.0

        # --- Chart Data ---
        
        # 1. Sales Trend (Daily/Weekly/Monthly)
        # Determine interval automatically based on period length if not specified, but let's stick to daily/weekly/monthly logic
        if period_length <= 31:
            interval = 'daily'
            trunc_func = TruncDay('date')
        elif period_length <= 180:
            interval = 'weekly'
            trunc_func = TruncWeek('date')
        else:
            interval = 'monthly'
            trunc_func = TruncMonth('date')

        sales_trend_data = []
        trend_agg = base_qs.annotate(period=trunc_func).values('period').annotate(total=Sum('total_final_amount')).order_by('period')
        for item in trend_agg:
            period = item['period']
            if period:
                period_date = period.date() if isinstance(period, datetime) else period
                if isinstance(period, str):
                    period_date = datetime.strptime(period[:10], '%Y-%m-%d').date()
                sales_trend_data.append({
                    "date": period_date.strftime('%Y-%m-%d'),
                    "sales": float(item['total'] or 0)
                })

        # 2. Payment Status Distribution
        status_dist = base_qs.values('payment_status').annotate(count=Count('id'), total=Sum('total_final_amount'))
        payment_status_distribution = [
            {"name": item['payment_status'], "value": float(item['total'] or 0)}
            for item in status_dist if item['payment_status']
        ]

        # 3. Top 10 Customers
        top_10_customers = base_qs.exclude(receiver__isnull=True).values('receiver__name').annotate(total=Sum('total_final_amount')).order_by('-total')[:10]
        top_customers = [
            {"name": item['receiver__name'], "sales": float(item['total'] or 0)}
            for item in top_10_customers
        ]

        # 4. Sales by State
        state_dist = base_qs.exclude(receiver__state__isnull=True).exclude(receiver__state='').values('receiver__state').annotate(total=Sum('total_final_amount')).order_by('-total')
        sales_by_state = [
            {"state": item['receiver__state'], "sales": float(item['total'] or 0)}
            for item in state_dist
        ]

        # 5. GST Trend (Monthly)
        gst_trend_data = []
        gst_agg = base_qs.annotate(month=TruncMonth('date')).values('month').annotate(total_gst=Sum('gst_final_amount')).order_by('month')
        for item in gst_agg:
            month = item['month']
            if month:
                month_date = month.date() if isinstance(month, datetime) else month
                if isinstance(month, str):
                    month_date = datetime.strptime(month[:10], '%Y-%m-%d').date()
                gst_trend_data.append({
                    "date": month_date.strftime('%Y-%m'),
                    "gst": float(item['total_gst'] or 0)
                })

        # 6. Payment Method Distribution
        method_dist = base_qs.exclude(payment_method__isnull=True).exclude(payment_method='').values('payment_method').annotate(total=Sum('total_final_amount'))
        payment_method_distribution = [
            {"name": item['payment_method'], "value": float(item['total'] or 0)}
            for item in method_dist
        ]

        # --- KPIs ---
        
        # Fastest Paying Customer & Average Payment Days
        # Since we don't have payment history linked directly to invoice lines easily without complex joins, we skip or approximate this if possible.
        # But we can approximate Average Payment Days if we had a payment date. Since we don't, we will set them to N/A for now.
        fastest_paying_customer = "N/A"
        average_payment_days = "N/A"

        # Repeat Customer %
        customers_in_period = base_qs.exclude(receiver__isnull=True).values('receiver_id').annotate(count=Count('id'))
        total_unique_customers = customers_in_period.count()
        repeat_customers = sum(1 for c in customers_in_period if c['count'] > 1)
        repeat_customer_pct = (repeat_customers / total_unique_customers * 100) if total_unique_customers > 0 else 0

        # New Customers (Customers whose first invoice is in this period)
        # To do this correctly, we find customers who have an invoice in this period, but no invoices before this period.
        if total_unique_customers > 0:
            customer_ids_in_period = [c['receiver_id'] for c in customers_in_period]
            customers_with_prior_invoices = Invoice.objects.filter(
                user_scope_q(request),
                invoice_type='sales',
                date__lt=start_date,
                receiver_id__in=customer_ids_in_period
            ).values_list('receiver_id', flat=True).distinct()
            
            new_customers_count = total_unique_customers - len(customers_with_prior_invoices)
        else:
            new_customers_count = 0

        return Response({
            "summary": {
                "total_sales": total_sales,
                "total_invoices": total_invoices,
                "paid_amount": paid_amount,
                "unpaid_amount": unpaid_amount,
                "overdue_amount": overdue_amount,
                "average_invoice_value": average_invoice_value,
                "gst_collected": gst_collected,
                "credit_notes_issued": credit_notes_issued,
                "credit_notes_amount": credit_notes_amount,
                "discount_given": discount_given,
                "top_customer": top_customer,
                "highest_sale_day": highest_sale_day,
                "sales_growth_pct": sales_growth_pct
            },
            "charts": {
                "sales_trend": sales_trend_data,
                "payment_status_distribution": payment_status_distribution,
                "top_customers": top_customers,
                "sales_by_state": sales_by_state,
                "gst_trend": gst_trend_data,
                "payment_method_distribution": payment_method_distribution
            },
            "kpis": {
                "fastest_paying_customer": fastest_paying_customer,
                "repeat_customer_pct": repeat_customer_pct,
                "new_customers": new_customers_count,
                "average_payment_days": average_payment_days
            }
        })
