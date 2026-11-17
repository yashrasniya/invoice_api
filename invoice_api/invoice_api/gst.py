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
import re
from calendar import monthrange
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Count, DecimalField, Q, Sum, Value
from django.db.models.functions import Coalesce

ZERO = Value(Decimal('0'), output_field=DecimalField(max_digits=20, decimal_places=2))

# Place-of-supply codes: 01-38 are the states/UTs, 96 Other Countries (the
# place of supply on an export invoice), 97 Other Territory, 99 Centre
# Jurisdiction. Anything else is a data-entry error. 96 is never a GSTIN
# prefix, so accounts/gst_utils.STATE_CODES (used to parse GSTINs) omits it.
FOREIGN_STATE_CODE = 96
VALID_STATE_CODES = set(range(1, 39)) | {FOREIGN_STATE_CODE, 97, 99}

# Names for the codes in use today (25 and 28 were merged away). Mirrors
# accounts/gst_utils.STATE_CODES, the frontend's constants/gst.js and the
# mobile app's constants/gst.ts; used to print the place of supply on PDFs.
STATE_NAMES = {
    1: 'Jammu and Kashmir', 2: 'Himachal Pradesh', 3: 'Punjab', 4: 'Chandigarh', 5: 'Uttarakhand',
    6: 'Haryana', 7: 'Delhi', 8: 'Rajasthan', 9: 'Uttar Pradesh', 10: 'Bihar', 11: 'Sikkim',
    12: 'Arunachal Pradesh', 13: 'Nagaland', 14: 'Manipur', 15: 'Mizoram', 16: 'Tripura',
    17: 'Meghalaya', 18: 'Assam', 19: 'West Bengal', 20: 'Jharkhand', 21: 'Odisha', 22: 'Chhattisgarh',
    23: 'Madhya Pradesh', 24: 'Gujarat', 26: 'Dadra and Nagar Haveli and Daman and Diu',
    27: 'Maharashtra', 29: 'Karnataka', 30: 'Goa', 31: 'Lakshadweep', 32: 'Kerala', 33: 'Tamil Nadu',
    34: 'Puducherry', 35: 'Andaman and Nicobar Islands', 36: 'Telangana', 37: 'Andhra Pradesh',
    38: 'Ladakh', 96: 'Other Countries', 97: 'Other Territory',
}

# Rates that legally exist, including the slabs retired in the Sept 2025
# rationalisation (12, 28) since older invoices still carry them and the
# 40% rate it introduced. Used only to flag, never to infer or block.
VALID_GST_SLABS = (Decimal('0'), Decimal('0.25'), Decimal('1.5'), Decimal('3'),
                   Decimal('5'), Decimal('12'), Decimal('18'), Decimal('28'),
                   Decimal('40'))

# Titles a company gives the line-item column that holds the GST *rate*.
# Matching used to be `input_title == 'GST'` exactly, so a column renamed
# "GST %" or "Tax" stopped being read as tax and was instead multiplied into
# the line total. "GST Amount" is deliberately not here: it is an amount.
_GST_COLUMN_KEYS = {'gst', 'gstrate', 'gstpercent', 'gstpercentage',
                    'tax', 'taxrate', 'taxpercent', 'taxpercentage', 'igst'}


def is_gst_column(title):
    """True when a line-item column with this title holds the GST rate."""
    key = re.sub(r'[^a-z]', '', str(title or '').lower())
    return key in _GST_COLUMN_KEYS


# Titles of the line-item column that holds the HSN/SAC code. "HNS" is how
# one shipped template spells it.
_HSN_COLUMN_KEYS = {'hsn', 'sac', 'hsncode', 'saccode', 'hsnsac', 'hsnsaccode', 'hsnorsac',
                    'hns', 'hnscode'}
HSN_RE = re.compile(r'^(\d{4}|\d{6}|\d{8})$')


def is_hsn_column(title):
    return re.sub(r'[^a-z]', '', str(title or '').lower()) in _HSN_COLUMN_KEYS


def hsn_error(value):
    """User-facing reason an HSN/SAC code is malformed, or None (blank is fine)."""
    code = re.sub(r'\s+', '', str(value or ''))
    if not code or HSN_RE.match(code):
        return None
    return 'HSN/SAC codes are 4, 6 or 8 digits (e.g. 8471 or 998314).'


def gst_rate_error(value):
    """User-facing message when `value` can't be a GST rate, else None.

    Blank is allowed (an untaxed line). Off-slab rates are allowed here and
    flagged on the GST report instead, so a rate this table doesn't know yet
    never blocks billing.
    """
    raw = str(value if value is not None else '').strip().rstrip('%').strip()
    if raw == '':
        return None
    try:
        rate = Decimal(raw)
    except Exception:
        return 'GST rate must be a number, e.g. 18.'
    if not rate.is_finite() or rate < 0 or rate > 100:
        return 'GST rate must be between 0 and 100.'
    return None


def is_standard_slab(value):
    raw = str(value if value is not None else '').strip().rstrip('%').strip()
    if raw == '':
        return True
    try:
        return Decimal(raw) in VALID_GST_SLABS
    except Exception:
        return False


def rupees(value):
    """GST returns are filed in whole rupees (s.170, CGST Act)."""
    return int(Decimal(value or 0).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def is_valid_state_code(code):
    try:
        return int(code) in VALID_STATE_CODES
    except (TypeError, ValueError):
        return False


# ── intra- vs inter-state ──────────────────────────────────────────────

def supply_type(invoice, home_state_code):
    """'intra', 'inter', or None when the states needed aren't known.

    Sales: we supply from our state to the place of supply (the invoice's own
    `place_of_supply`, else the customer's state). Purchases: the vendor
    supplies from their state to the place of supply (the invoice's, else
    ours). Same fallbacks as `split_tax`, so a PDF and the GST report agree.
    """
    if getattr(invoice, 'invoice_type', 'sales') == 'purchase':
        party = invoice.vendor or invoice.receiver
        origin = getattr(party, 'state_code', None) if party else None
        dest = invoice.place_of_supply or home_state_code
    else:
        origin = home_state_code
        party = invoice.receiver
        # supplies to an SEZ and exports are inter-state whatever the states
        # (IGST Act s.7(5)): always IGST
        if getattr(party, 'gst_treatment', '') in ('sez', 'overseas'):
            return 'inter'
        dest = invoice.place_of_supply or (getattr(party, 'state_code', None) if party else None)
    if not (is_valid_state_code(origin) and is_valid_state_code(dest)):
        return None
    return 'intra' if int(origin) == int(dest) else 'inter'


def taxable_value(total, gst, reverse_charge=False):
    """An invoice's taxable value from its stored totals.

    Normally the total includes the GST, so taxable = total − gst. On a
    reverse-charge invoice the supplier collects no GST: the total is what the
    recipient pays the supplier and the GST is paid by the recipient on top,
    so the total *is* the taxable value.
    """
    total = Decimal(total or 0)
    return total if reverse_charge else total - Decimal(gst or 0)


def has_valid_lut(company, on_date):
    """Whether the company's LUT covers `on_date` (exports/SEZ without IGST)."""
    if not company or not (getattr(company, 'lut_number', '') or '').strip() or not on_date:
        return False
    start, end = getattr(company, 'lut_valid_from', None), getattr(company, 'lut_valid_to', None)
    return bool(start and end and start <= on_date <= end)


def tax_heads(taxable, gst, supply):
    """Footer tax fields for a printed invoice.

    Inter-state supply is IGST only; intra-state is CGST + SGST. When the
    supply type is unknown (a state code missing) the old CGST/SGST halves
    are kept, matching what such invoices have always printed — the GST
    report separately lists them as unclassified.
    """
    gst = round(float(gst or 0), 2)
    taxable = float(taxable or 0)
    rate = round(gst / taxable * 100, 2) if taxable else 0
    if supply == 'inter':
        return {
            'supply_type': 'inter',
            'center_gst_amount': 0, 'state_gst_amount': 0, 'igst_amount': gst,
            'gst': rate, 'center_gst': 0, 'state_gst': 0, 'igst': rate,
        }
    cgst = round(gst / 2, 2)
    return {
        'supply_type': supply or '',
        # SGST takes the remainder so the pair sums to the GST printed
        'center_gst_amount': cgst, 'state_gst_amount': round(gst - cgst, 2),
        'igst_amount': 0,
        'gst': rate, 'center_gst': round(rate / 2, 2),
        'state_gst': round(rate - round(rate / 2, 2), 2), 'igst': 0,
    }


# Templates designed before IGST was printed label their two tax slots
# "CGST"/"SGST". For an inter-state invoice the CGST slot is relabelled to
# IGST and the SGST slot dropped, rather than printing CGST 0 / SGST 0 with
# the tax missing from the face of the invoice.
_CGST_AMT_RE = re.compile(r'CGST([^<{]*)\{\{\s*footer\.center_gst_amount\s*\}\}')
_CGST_PCT_RE = re.compile(r'CGST([^<{]*)\{\{\s*footer\.center_gst\s*\}\}')
_SGST_RE = re.compile(r'SGST[^<{]*\{\{\s*footer\.state_gst(?:_amount)?\s*\}\}\s*(?:/-|%)?')


def adapt_html_for_igst(html):
    """Relabel a CGST/SGST-only HTML template for an inter-state invoice.

    Templates that already reference IGST are returned untouched.
    """
    if 'igst' in html.lower():
        return html
    html = _CGST_AMT_RE.sub(lambda m: 'IGST' + m.group(1) + '{{ footer.igst_amount }}', html)
    html = _CGST_PCT_RE.sub(lambda m: 'IGST' + m.group(1) + '{{ footer.igst }}', html)
    return _SGST_RE.sub('', html)


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

    Place of supply is the invoice's own `place_of_supply` when set, otherwise
    the customer's state. Where either the seller's or
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

    # An invoice-level place of supply wins over the customer's registered
    # state; with neither set the row stays unclassified rather than guessed.
    rows = (sales_qs
            .annotate(_pos=Coalesce('place_of_supply', 'receiver__state_code'))
            .values_list('_pos', 'total_final_amount', 'gst_final_amount', 'receiver__gst_treatment'))

    for row in rows:
        state_code, total, gst = row[:3]
        treatment = row[3] if len(row) > 3 else ''
        gst = Decimal(gst or 0)
        taxable = Decimal(total or 0) - gst

        if treatment in ('sez', 'overseas'):
            # always IGST (IGST Act s.7(5)), whatever the state codes say
            result['igst'] += gst
            result['inter_taxable'] += taxable
        elif not home_ok or not is_valid_state_code(state_code):
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
    """Credit and debit note values in the period, and their effect on tax.

    A note on a customer (or on a sales invoice) adjusts output tax: a credit
    note reduces it, a debit note adds to it. A note on a vendor (or on a
    purchase invoice) adjusts input credit the same way. Only notes with
    `gst_amount` recorded are netted; the rest are counted in
    `notes_without_gst` so the report can say the liability is incomplete
    instead of treating the whole note value as tax.
    """
    notes = notes_qs.filter(date__gte=start, date__lte=end)
    purchase_side = Q(vendor__isnull=False) | Q(invoice__invoice_type='purchase')
    credit, debit = Q(note_type='credit'), Q(note_type='debit')

    def tax(side, kind):
        return Coalesce(Sum('gst_amount', filter=side & kind), ZERO)

    agg = notes.aggregate(
        credit=Coalesce(Sum('amount', filter=credit), ZERO),
        credit_count=Count('id', filter=credit),
        debit=Coalesce(Sum('amount', filter=debit), ZERO),
        debit_count=Count('id', filter=debit),
        out_credit=tax(~purchase_side, credit), out_debit=tax(~purchase_side, debit),
        in_credit=tax(purchase_side, credit), in_debit=tax(purchase_side, debit),
        without_gst=Count('id', filter=Q(gst_amount__isnull=True)),
    )
    return {
        'credit_note_value': rupees(agg['credit']),
        'credit_note_count': agg['credit_count'],
        'debit_note_value': rupees(agg['debit']),
        'debit_note_count': agg['debit_count'],
        # unrounded: the caller rounds once, after netting
        'output_tax_adjustment': agg['out_debit'] - agg['out_credit'],
        'input_tax_adjustment': agg['in_debit'] - agg['in_credit'],
        'notes_without_gst': agg['without_gst'],
    }


# ── data quality ───────────────────────────────────────────────────────

def _is_number(value):
    try:
        Decimal(str(value))
        return True
    except Exception:
        return False


def off_slab_rates(sales_qs):
    """{rate: line count} for GST-rate cells on these invoices that aren't a
    standard slab. Column titles are free text, so they are matched here in
    Python after a cheap prefilter in SQL."""
    from invoice.models import Product_properties
    rows = (Product_properties.objects
            .filter(product__invoice__in=sales_qs)
            .filter(Q(new_product_in_frontend__input_title__icontains='gst')
                    | Q(new_product_in_frontend__input_title__icontains='tax'))
            .values_list('new_product_in_frontend__input_title', 'value'))
    found = {}
    for title, value in rows:
        if is_gst_column(title) and not is_standard_slab(value):
            key = str(value).strip().rstrip('%').strip()
            found[key] = found.get(key, 0) + 1
    return found


def data_quality(company, sales_qs, purchase_qs, split, today=None, notes=None,
                 off_slab=None):
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
                       "neither the invoice's place of supply nor the customer's state "
                       "code is valid. This amount is excluded from the CGST/SGST and "
                       "IGST figures."),
            'fix': 'Customers → State Code, or set Place of supply on the invoice',
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

    if notes and notes.get('notes_without_gst'):
        n = notes['notes_without_gst']
        issues.append({
            'level': 'warning',
            'code': 'notes_without_gst',
            'title': f"{n} credit/debit note(s) in this period have no GST amount",
            'detail': ("Notes without a GST amount can't be netted into the tax figures, "
                       "so net GST payable ignores them. A credit note to a customer "
                       "normally reduces what you owe."),
            'fix': 'Record the GST amount on each credit/debit note',
        })

    # {rate: line count} from off_slab_rates(), computed by the caller
    if off_slab:
        rates = ', '.join(f'{r}%' for r in sorted(off_slab, key=lambda r: Decimal(r) if _is_number(r) else Decimal('-1')))
        issues.append({
            'level': 'warning',
            'code': 'non_standard_rate',
            'title': f"{sum(off_slab.values())} sales line(s) use a non-standard GST rate",
            'detail': (f"Rates found: {rates}. GST is charged at "
                       + ', '.join(f'{r}%' for r in VALID_GST_SLABS)
                       + ". Check these lines for a typo."),
            'fix': 'Open the invoices and correct the GST % on those lines',
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
