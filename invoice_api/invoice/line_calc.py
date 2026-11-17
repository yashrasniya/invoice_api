"""Server-side line-item and invoice totals.

Clients (the web app's calculateProductTotals, the mobile app's
calculateLine) compute a line's amounts from the company's configured
columns and send them. Those values used to be stored as sent, and the
invoice's `gst_final_amount` / `total_final_amount` likewise — so a renamed
GST column, a stale client or a hand-made API call could store tax that no
line supports. Every write path for lines and invoices now recomputes here.

The arithmetic is a 1:1 port of the mobile app's `calculateLine`:

* the running total starts at 1 so plain columns can multiply into it;
* plain calculable columns (no formula) multiply first, formula columns
  (+ - / %+ %-) apply after, optionally outside the GST base;
* GST is `rate% × running total`, read from the GST-rate column;
* a line with no amount typed into any calculable column is worth 0, not 1.

A line with no calculable inputs at all (e.g. a purchase line imported from
a scanned bill, which carries amounts but no qty/rate) keeps its stored
amounts: there is nothing to recompute it from.
"""
from decimal import Decimal, ROUND_HALF_UP

from invoice_api.gst import is_gst_column

CENT = Decimal('0.01')


def _num(value):
    try:
        x = float(value)
    except (TypeError, ValueError):
        return 0.0
    return x if x == x and x not in (float('inf'), float('-inf')) else 0.0


def _money(x):
    return Decimal(str(x if x == x else 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def calculate_line(props):
    """(total_amount, gst_amount) as Decimals, or None when nothing to compute.

    `props` is an iterable of (column, value), column being a
    `new_product_in_frontend` row.
    """
    detail = calculate_line_detail(props)
    return None if detail is None else (detail['total'], detail['gst'])


def calculate_line_detail(props):
    """Like `calculate_line`, plus the parts a GST return needs.

    Returns {'total', 'gst', 'taxable', 'rate'} (Decimals; rate is None when
    the line has no GST-rate cell), or None when there is nothing to compute.
    `taxable` is the GST base: charges added outside it (`on_with_out_gst_amount`)
    are in `total` but not taxable.
    """
    props = list(props)
    has_input = any(c.is_calculable and not is_gst_column(c.input_title)
                    and str(v if v is not None else '').strip() != ''
                    for c, v in props)
    if not has_input:
        return None

    total, extra = 1.0, 0.0
    # plain multipliers first, then formula columns (stable, like the clients)
    for c, value in sorted(props, key=lambda cv: 1 if cv[0].formula else 0):
        if not c.is_calculable or is_gst_column(c.input_title):
            continue
        val = _num(value)
        f = c.formula
        if f:
            if f == '+':
                if c.on_with_out_gst_amount: extra += val
                else: total += val
            elif f == '-':
                if c.on_with_out_gst_amount: extra -= val
                else: total -= val
            elif f == '/':
                total /= val or 1
            elif f in ('%+', '%-'):
                x = (val / 100) * total * (1 if f == '%+' else -1)
                if c.on_with_out_gst_amount: extra += x
                else: total += x
        elif str(value if value is not None else '').strip():
            total *= val

    gst, rate = 0.0, None
    for c, value in props:
        if is_gst_column(c.input_title):
            raw = str(value if value is not None else '').strip().rstrip('%').strip()
            gst = total * (_num(raw) / 100) if raw else 0.0
            rate = Decimal(str(_num(raw))) if raw else Decimal('0')
            break

    return {'total': _money(total + gst + extra), 'gst': _money(gst),
            'taxable': _money(total), 'rate': rate}


def recompute_product(product):
    """Recompute a line from its properties; returns True if it changed."""
    props = [(p.new_product_in_frontend, p.value)
             for p in product.product_properties.select_related('new_product_in_frontend')]
    result = calculate_line(props)
    if result is None:
        return False
    total, gst = result
    if product.total_amount == total and product.gst_amount == gst:
        return False
    product.total_amount, product.gst_amount = total, gst
    product.save(update_fields=['total_amount', 'gst_amount'])
    return True


def recompute_invoice_totals(invoice):
    """Invoice totals = sum of its lines (minus their GST on a reverse-charge
    invoice). An invoice with no lines (header-only bills, e.g. a scanned
    purchase) keeps the totals it was given."""
    lines = list(invoice.products.values_list('total_amount', 'gst_amount'))
    if not lines:
        return False
    total = sum((Decimal(t or 0) for t, _ in lines), Decimal('0')).quantize(CENT)
    gst = sum((Decimal(g or 0) for _, g in lines), Decimal('0')).quantize(CENT)
    if invoice.reverse_charge:
        # the recipient pays the GST: the supplier is owed the lines without it
        total -= gst
    if invoice.total_final_amount == total and invoice.gst_final_amount == gst:
        return False
    invoice.total_final_amount, invoice.gst_final_amount = total, gst
    invoice.save(update_fields=['total_final_amount', 'gst_final_amount'])
    return True


def recompute_for_product(product):
    """After a line changes: the line itself, then every invoice holding it."""
    recompute_product(product)
    for invoice in product.invoice_set.all():
        recompute_invoice_totals(invoice)
