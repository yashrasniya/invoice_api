"""
Shared aggregation helpers for the customer-facing dashboard.

Kept out of the views so the KPI header (`user_info/`) and the richer
widgets (`dashboard/`) compute the same numbers the same way.

Two rules everything here follows:

* **Sales means sales.** Every revenue/GST figure filters
  `invoice_type='sales'`; purchase bills are a cost, not turnover.
* **No fabricated denominators.** A percentage against an empty base
  period is `None` — the UI renders that as "new", not as "+49900%".
"""
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import (
    BooleanField, Case, Count, DecimalField, F, Q, Sum, Value, When)
from django.db.models.functions import Coalesce

ZERO = Value(Decimal('0'), output_field=DecimalField(max_digits=20, decimal_places=2))

# statuses that still owe us money
OPEN_STATUSES = ('unpaid', 'partially_paid', 'overdue')

# Invoice has no due_date column, and nothing in the product ever flips a
# bill to 'overdue' — so the overdue figure is derived from age instead:
# an unpaid bill older than this many days counts as past due. Override
# with INVOICE_OVERDUE_AFTER_DAYS in settings once real payment terms are
# captured per invoice.
OVERDUE_AFTER_DAYS = getattr(settings, 'INVOICE_OVERDUE_AFTER_DAYS', 30)


def _month_span(year, month):
    return (date(year, month, 1),
            date(year, month, monthrange(year, month)[1]))


def _shift_month(year, month, delta):
    idx = (year * 12 + (month - 1)) + delta
    return idx // 12, (idx % 12) + 1


def fy_bounds(today):
    """Indian financial year: 1 Apr → 31 Mar."""
    start_year = today.year if today.month >= 4 else today.year - 1
    return date(start_year, 4, 1), date(start_year + 1, 3, 31)


def period_bounds(rng, today=None):
    """(current, previous, label) date ranges for a dashboard range key."""
    today = today or date.today()

    if rng == 'last_month':
        py, pm = _shift_month(today.year, today.month, -1)
        cur = _month_span(py, pm)
        ppy, ppm = _shift_month(py, pm, -1)
        prev = _month_span(ppy, ppm)
        label = cur[0].strftime('%B %Y')

    elif rng == 'this_fy':
        cur = fy_bounds(today)
        prev = (date(cur[0].year - 1, 4, 1), date(cur[0].year, 3, 31))
        label = f"FY {cur[0].year}-{str(cur[1].year)[2:]}"

    elif rng == 'last_30':
        cur = (today - timedelta(days=29), today)
        prev = (today - timedelta(days=59), today - timedelta(days=30))
        label = 'Last 30 days'

    else:  # this_month (default)
        cur = _month_span(today.year, today.month)
        py, pm = _shift_month(today.year, today.month, -1)
        prev = _month_span(py, pm)
        label = cur[0].strftime('%B %Y')

    return cur, prev, label


def pct_change(current, previous):
    """Growth %, or None when there is no baseline to grow from.

    Returning None is deliberate: a first month of trading is not
    "+infinity% growth", it is simply not comparable, and the UI needs to
    be able to tell the difference.
    """
    if not previous:
        return None
    return round(((float(current) - float(previous)) / float(previous)) * 100, 1)


def sales_totals(qs, start, end):
    """Turnover, GST and invoice count for a date window."""
    agg = qs.filter(date__gte=start, date__lte=end).aggregate(
        total=Coalesce(Sum('total_final_amount'), ZERO),
        gst=Coalesce(Sum('gst_final_amount'), ZERO),
        count=Count('id'),
    )
    return {
        'total': round(float(agg['total'])),
        'gst': round(float(agg['gst'])),
        'count': agg['count'],
    }


def open_invoices_qs(qs, today=None):
    """Invoices that still owe money, with `due` annotated.

    `due` is billed value minus payments actually received against that
    invoice, so a partially paid bill contributes only its remainder, and
    a bill whose payments already cover it drops out entirely (its status
    may simply not have been updated yet).

    Also annotates `is_overdue`: either the status was set explicitly, or
    the bill has aged past `OVERDUE_AFTER_DAYS` while still unpaid. The
    derived half matters because nothing in the product currently sets the
    'overdue' status on its own.
    """
    today = today or date.today()
    cutoff = today - timedelta(days=OVERDUE_AFTER_DAYS)

    return (qs.filter(payment_status__in=OPEN_STATUSES)
              .annotate(
                  paid=Coalesce(
                      Sum('payments__amount',
                          filter=Q(payments__payment_type='received')),
                      ZERO),
              )
              .annotate(
                  due=Coalesce(F('total_final_amount'), ZERO) - F('paid'),
                  is_overdue=Case(
                      When(payment_status='overdue', then=Value(True)),
                      When(date__lt=cutoff, then=Value(True)),
                      default=Value(False),
                      output_field=BooleanField(),
                  ),
              )
              .filter(due__gt=0))


def outstanding_totals(qs, today=None):
    """Money still owed to the business, and the overdue slice of it."""
    open_qs = open_invoices_qs(qs, today)

    agg = open_qs.aggregate(
        receivable=Coalesce(Sum('due'), ZERO),
        receivable_count=Count('id'),
        overdue=Coalesce(Sum('due', filter=Q(is_overdue=True)), ZERO),
        overdue_count=Count('id', filter=Q(is_overdue=True)),
    )

    return {
        'receivable_amount': round(float(agg['receivable'])),
        'receivable_count': agg['receivable_count'],
        'overdue_amount': round(float(agg['overdue'])),
        'overdue_count': agg['overdue_count'],
        'overdue_after_days': OVERDUE_AFTER_DAYS,
    }


def monthly_trend(qs, today=None, months=6):
    """Turnover per month for the last `months` months, oldest first."""
    today = today or date.today()
    first_year, first_month = _shift_month(today.year, today.month, -(months - 1))
    window_start = date(first_year, first_month, 1)
    # run to month end, not to today — otherwise the final bar silently
    # disagrees with the Sales KPI for the same month
    window_end = _month_span(today.year, today.month)[1]

    rows = (qs.filter(date__gte=window_start, date__lte=window_end)
              .values_list('date', 'total_final_amount', 'gst_final_amount'))

    buckets = {}
    for d, total, gst in rows:
        if not d:
            continue
        key = (d.year, d.month)
        acc = buckets.setdefault(key, [Decimal('0'), Decimal('0'), 0])
        acc[0] += Decimal(total or 0)
        acc[1] += Decimal(gst or 0)
        acc[2] += 1

    out = []
    for i in range(months):
        y, m = _shift_month(first_year, first_month, i)
        total, gst, count = buckets.get((y, m), (Decimal('0'), Decimal('0'), 0))
        out.append({
            'label': date(y, m, 1).strftime('%b'),
            'month': f'{y}-{m:02d}',
            'total': round(float(total)),
            'gst': round(float(gst)),
            'count': count,
        })
    return out


def top_customers(qs, start, end, limit=5):
    rows = (qs.filter(date__gte=start, date__lte=end, receiver__isnull=False)
              .values('receiver_id', 'receiver__name')
              .annotate(total=Coalesce(Sum('total_final_amount'), ZERO),
                        count=Count('id'))
              .order_by('-total')[:limit])
    return [{
        'id': r['receiver_id'],
        'name': r['receiver__name'] or 'Unnamed',
        'total': round(float(r['total'])),
        'count': r['count'],
    } for r in rows]


def payment_method_split(payments_qs, start, end):
    """Cash actually received in the window, grouped by method.

    Deliberately reads `Payment` rows rather than grouping invoices by
    `Invoice.payment_method`: an unpaid invoice carries a method but no
    money, and counting it here would report cash the business never got.
    """
    rows = (payments_qs.filter(payment_type='received',
                               date__gte=start, date__lte=end)
                       .values('payment_method')
                       .annotate(total=Coalesce(Sum('amount'), ZERO),
                                 count=Count('id'))
                       .order_by('-total'))
    return [{
        'method': r['payment_method'] or 'unrecorded',
        'total': round(float(r['total'])),
        'count': r['count'],
    } for r in rows if r['total']]


# GST filing deadlines (day of the month following the return period)
GST_DUE_DAYS = (('GSTR-1', 11), ('GSTR-3B', 20))


def gst_due_dates(today=None):
    """Next GSTR-1 / GSTR-3B deadlines for the just-closed return period."""
    today = today or date.today()
    out = []
    for form, day in GST_DUE_DAYS:
        due = date(today.year, today.month, day)
        period_y, period_m = _shift_month(today.year, today.month, -1)
        if today > due:  # this month's deadline has passed → next one
            ny, nm = _shift_month(today.year, today.month, 1)
            due = date(ny, nm, day)
            period_y, period_m = today.year, today.month
        out.append({
            'form': form,
            'due_date': due.isoformat(),
            'period': date(period_y, period_m, 1).strftime('%b %Y'),
            'days_left': (due - today).days,
        })
    return out
