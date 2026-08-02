"""
GST report helpers.

The GST summary has to answer a narrower question than a sales report: not
"how did we do" but "what goes in the return". That means three things the
old summary didn't do:

* **Periods are calendar months / quarters, never a rolling window.** A
  rolling 30 days can coincidentally match a filing period (and then
  silently stop matching the next day), which is worse than being visibly
  wrong.
* **Tax is split CGST/SGST vs IGST.** A single "output GST" number cannot
  be entered into GSTR-1 or 3B.
* **Credit and debit notes move the liability.** A credit note issued to a
  customer reduces output tax; ignoring them overstates what is owed.

Where the source data can't support an answer, these helpers put the
amount in an `unclassified` bucket and raise a warning rather than
guessing — an unsupported split silently rendered as CGST/SGST would be
filed, and filing a guess is worse than filing nothing.
"""
from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce

ZERO = Value(Decimal('0'), output_field=DecimalField(max_digits=20, decimal_places=2))

# GSTIN state codes: 01-38 are the states/UTs, 97 Other Territory,
# 99 Centre Jurisdiction. Anything else is a data-entry error.
VALID_STATE_CODES = set(range(1, 39)) | {97, 99}

# Rates that legally exist. Used only to validate, never to infer.
VALID_GST_SLABS = (Decimal('0'), Decimal('0.25'), Decimal('3'),
                   Decimal('5'), Decimal('12'), Decimal('18'), Decimal('28'))


def rupees(value):
    """GST returns are filed in whole rupees (s.170, CGST Act)."""
    return int(Decimal(value or 0).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def is_valid_state_code(code):
    try:
        return int(code) in VALID_STATE_CODES
    except (TypeError, ValueError):
        return False


# ── periods ────────────────────────────────────────────────────────────

def _month(year, month):
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def _shift(year, month, delta):
    idx = year * 12 + (month - 1) + delta
    return idx // 12, (idx % 12) + 1


def _quarter_of(today):
    """Indian FY quarters: Apr-Jun, Jul-Sep, Oct-Dec, Jan-Mar."""
    q_start_month = ((today.month - 4) % 12) // 3 * 3 + 4
    year = today.year if today.month >= 4 else today.year - 1
    if q_start_month > 12:
        q_start_month -= 12
    # normalise: Jan-Mar belongs to the FY that began the previous April
    if today.month <= 3:
        q_start_month, year = 1, today.year
    return year, q_start_month


def gst_period_bounds(period, today=None):
    """(start, end, label) for a GST filing period key."""
    today = today or date.today()

    if period == 'last_month':
        y, m = _shift(today.year, today.month, -1)
        s, e = _month(y, m)
        return s, e, s.strftime('%B %Y')

    if period == 'this_quarter' or period == 'last_quarter':
        y, qm = _quarter_of(today)
        if period == 'last_quarter':
            y, qm = _shift(y, qm, -3)
        s = date(y, qm, 1)
        ey, em = _shift(y, qm, 2)
        e = _month(ey, em)[1]
        return s, e, f"{s.strftime('%b')}–{e.strftime('%b %Y')}"

    if period == 'this_fy':
        sy = today.year if today.month >= 4 else today.year - 1
        return (date(sy, 4, 1), date(sy + 1, 3, 31),
                f"FY {sy}-{str(sy + 1)[2:]}")

    # this_month (default)
    s, e = _month(today.year, today.month)
    return s, e, s.strftime('%B %Y')


# ── tax split ──────────────────────────────────────────────────────────

def split_tax(sales_qs, home_state_code):
    """Split output tax into CGST/SGST (intra-state) and IGST (inter-state).

    Place of supply is the customer's state. Where either the seller's or
    the buyer's state code is missing or invalid the tax lands in
    `unclassified` — it is not guessed into either bucket.
    """
    result = {
        'cgst': Decimal('0'), 'sgst': Decimal('0'), 'igst': Decimal('0'),
        'unclassified': Decimal('0'),
        'intra_taxable': Decimal('0'), 'inter_taxable': Decimal('0'),
        'unclassified_taxable': Decimal('0'),
        'unclassified_invoices': 0,
    }

    home_ok = is_valid_state_code(home_state_code)
    home = int(home_state_code) if home_ok else None

    rows = sales_qs.values_list('receiver__state_code',
                                'total_final_amount', 'gst_final_amount')

    for state_code, total, gst in rows:
        gst = Decimal(gst or 0)
        taxable = Decimal(total or 0) - gst

        if not home_ok or not is_valid_state_code(state_code):
            result['unclassified'] += gst
            result['unclassified_taxable'] += taxable
            result['unclassified_invoices'] += 1
        elif int(state_code) == home:
            half = gst / 2
            result['cgst'] += half
            result['sgst'] += gst - half      # keep the pair summing exactly
            result['intra_taxable'] += taxable
        else:
            result['igst'] += gst
            result['inter_taxable'] += taxable

    return result


# ── notes ──────────────────────────────────────────────────────────────

def note_totals(notes_qs, start, end):
    """Credit and debit note values in the period.

    `CreditDebitNote` stores a single `amount` with no tax component, so
    the note value is reported separately rather than being silently
    treated as tax — see the caller's `notes_reduce_liability` flag.
    """
    agg = notes_qs.filter(date__gte=start, date__lte=end).aggregate(
        credit=Coalesce(Sum('amount', filter=Q(note_type='credit')), ZERO),
        credit_count=Count('id', filter=Q(note_type='credit')),
        debit=Coalesce(Sum('amount', filter=Q(note_type='debit')), ZERO),
        debit_count=Count('id', filter=Q(note_type='debit')),
    )
    return {
        'credit_note_value': rupees(agg['credit']),
        'credit_note_count': agg['credit_count'],
        'debit_note_value': rupees(agg['debit']),
        'debit_note_count': agg['debit_count'],
    }


# ── data quality ───────────────────────────────────────────────────────

def data_quality(company, sales_qs, purchase_qs, split, today=None):
    """Problems that make the numbers on this page untrustworthy.

    Surfaced to the user rather than swallowed: a GST report that looks
    complete but silently omits input tax is a report someone will file.
    """
    today = today or date.today()
    issues = []

    home = getattr(company, 'state_code', None) if company else None
    if not is_valid_state_code(home):
        issues.append({
            'level': 'error',
            'code': 'company_state_code',
            'title': 'Your company state code is missing or invalid',
            'detail': (f"Found {home!r}. GST state codes run 01–38 (plus 97 and 99). "
                       "Until this is corrected, sales cannot be classified as "
                       "intra-state (CGST+SGST) or inter-state (IGST)."),
            'fix': 'My Company → State Code',
        })

    if split['unclassified_invoices']:
        issues.append({
            'level': 'error' if split['unclassified'] else 'warning',
            'code': 'customer_state_code',
            'title': f"{split['unclassified_invoices']} invoice(s) could not be classified",
            'detail': (f"₹{rupees(split['unclassified']):,} of tax is unclassified because "
                       "the customer has no valid state code. This amount is excluded "
                       "from the CGST/SGST and IGST figures."),
            'fix': 'Customers → State Code',
        })

    zero_gst = purchase_qs.filter(Q(gst_final_amount__isnull=True) |
                                  Q(gst_final_amount=0))
    zero_gst_count = zero_gst.count()
    if zero_gst_count:
        value = zero_gst.aggregate(v=Coalesce(Sum('total_final_amount'), ZERO))['v']
        issues.append({
            'level': 'warning',
            'code': 'purchases_without_gst',
            'title': f"{zero_gst_count} purchase invoice(s) have no GST recorded",
            'detail': (f"₹{rupees(value):,} of purchases carry zero input tax. If GST was "
                       "actually paid on these, your input credit is understated and this "
                       "report overstates what you owe."),
            'fix': 'Purchases → edit the invoice and enter the GST amount',
        })

    future_sales = sales_qs.filter(date__gt=today).count()
    future_purchases = purchase_qs.filter(date__gt=today).count()
    if future_sales or future_purchases:
        issues.append({
            'level': 'warning',
            'code': 'future_dated',
            'title': 'Some invoices are dated in the future',
            'detail': (f"{future_sales} sale(s) and {future_purchases} purchase(s) are dated "
                       "after today. They will drop out of period reports until that date "
                       "arrives, then appear retroactively."),
            'fix': 'Check the invoice dates',
        })

    return issues
