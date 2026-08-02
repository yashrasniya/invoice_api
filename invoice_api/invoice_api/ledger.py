"""
Party ledger (customer receivables / vendor payables) and the analysis
that makes it useful rather than just a list of rows.

Three things this module is careful about, because the previous version
wasn't:

* **Decimal, not float.** A running balance is an accumulator; running it
  through binary floats drifts, and a ledger that doesn't tie out is worse
  than no ledger.
* **Transactions are matched by party *or* by their invoice's party.** A
  receipt recorded against an invoice but without the customer FK set
  would otherwise be invisible and silently overstate what is owed.
* **Ageing is derived, not stored.** There is no due-date column, so age
  is measured from the invoice date and the window is stated in the
  response rather than assumed by the reader.
"""
from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.db.models import Q

# how the outstanding balance is bucketed, in days since the invoice date
AGEING_BUCKETS = ((0, 30), (31, 60), (61, 90), (91, None))

OPEN_STATUSES = ('unpaid', 'partially_paid', 'overdue')

D0 = Decimal('0')


def _d(value):
    return Decimal(str(value)) if value is not None else D0


def bucket_label(lo, hi):
    return f'{lo}-{hi} days' if hi else f'{lo}+ days'


# ── scoping ────────────────────────────────────────────────────────────

def party_filters(entity_type, entity_id):
    """Q objects matching a party's own rows *and* rows reached via invoice.

    `Payment.customer` / `CreditDebitNote.customer` are nullable, so a row
    can legitimately identify its party only through `invoice.receiver`.
    Matching on both is what stops those rows going missing.
    """
    if entity_type == 'customer':
        return {
            'invoice': Q(receiver_id=entity_id, invoice_type='sales'),
            'payment': Q(customer_id=entity_id) | Q(invoice__receiver_id=entity_id),
            'note': Q(customer_id=entity_id) | Q(invoice__receiver_id=entity_id),
        }
    return {
        'invoice': Q(vendor_id=entity_id, invoice_type='purchase'),
        'payment': Q(vendor_id=entity_id) | Q(invoice__vendor_id=entity_id),
        'note': Q(vendor_id=entity_id) | Q(invoice__vendor_id=entity_id),
    }


# ── the ledger itself ──────────────────────────────────────────────────

#: sort order within a single date, so the running balance reads the way an
#: accountant would write it: the invoice, then money against it, then
#: adjustments.
VCH_ORDER = {'Sales': 0, 'Purchase': 0, 'Receipt': 1, 'Payment': 1,
             'Debit Note': 2, 'Credit Note': 2}


def build_transactions(entity_type, invoices, payments, notes):
    """Ledger rows for one party, sorted, with a running balance.

    For a customer, debit increases what they owe; for a vendor, credit
    increases what we owe. Both are returned as positive numbers in their
    respective columns.
    """
    is_customer = entity_type == 'customer'
    rows = []

    for inv in invoices:
        amount = _d(inv.total_final_amount)
        rows.append({
            'date': inv.date.isoformat() if inv.date else None,
            'particulars': f"Invoice #{inv.invoice_number or 'N/A'}",
            'vch_type': 'Sales' if is_customer else 'Purchase',
            'vch_no': inv.invoice_number,
            'debit': amount if is_customer else D0,
            'credit': amount if not is_customer else D0,
            'invoice_id': inv.id,
        })

    for pay in payments:
        amount = _d(pay.amount)
        received = pay.payment_type == 'received'
        rows.append({
            'date': pay.date.isoformat() if pay.date else None,
            'particulars': f"Payment {pay.payment_type} ({pay.payment_method or 'N/A'})",
            'vch_type': 'Receipt' if received else 'Payment',
            'vch_no': pay.reference_number,
            'debit': amount if (not is_customer and not received) else D0,
            'credit': amount if (is_customer and received) else D0,
            'invoice_id': pay.invoice_id,
        })

    for note in notes:
        amount = _d(note.amount)
        credit_note = note.note_type == 'credit'
        # a credit note reduces what a customer owes; for a vendor it's the
        # mirror image
        as_debit = (is_customer and not credit_note) or (not is_customer and credit_note)
        rows.append({
            'date': note.date.isoformat() if note.date else None,
            'particulars': f"{'Credit' if credit_note else 'Debit'} note"
                           + (f" ({note.reason})" if note.reason else ''),
            'vch_type': 'Credit Note' if credit_note else 'Debit Note',
            'vch_no': note.note_number,
            'debit': amount if as_debit else D0,
            'credit': amount if not as_debit else D0,
            'invoice_id': note.invoice_id,
        })

    # undated rows sort last rather than silently leading the ledger
    rows.sort(key=lambda r: (r['date'] is None, r['date'] or '',
                             VCH_ORDER.get(r['vch_type'], 9),
                             r['vch_no'] or ''))
    return rows


def apply_running_balance(rows, opening, entity_type):
    balance = _d(opening)
    is_customer = entity_type == 'customer'
    for row in rows:
        if is_customer:
            balance += row['debit'] - row['credit']
        else:
            balance += row['credit'] - row['debit']
        row['balance'] = balance
    return balance


def opening_balance(entity_type, invoices, payments, notes, before):
    """Balance carried into the period, from everything dated earlier."""
    is_customer = entity_type == 'customer'

    inv_total = sum((_d(i.total_final_amount)
                     for i in invoices.filter(date__lt=before)), D0)
    prev_pay = payments.filter(date__lt=before)
    received = sum((_d(p.amount) for p in prev_pay
                    if p.payment_type == 'received'), D0)
    made = sum((_d(p.amount) for p in prev_pay if p.payment_type == 'made'), D0)
    prev_notes = notes.filter(date__lt=before)
    credit = sum((_d(n.amount) for n in prev_notes if n.note_type == 'credit'), D0)
    debit = sum((_d(n.amount) for n in prev_notes if n.note_type == 'debit'), D0)

    if is_customer:
        return inv_total - received - credit + debit
    return inv_total - made - debit + credit


# ── analysis ───────────────────────────────────────────────────────────

def outstanding_by_invoice(invoices, payments_by_invoice, today=None):
    """Every still-open invoice with what remains on it and how old it is."""
    today = today or date.today()
    out = []

    for inv in invoices.filter(payment_status__in=OPEN_STATUSES):
        billed = _d(inv.total_final_amount)
        paid = payments_by_invoice.get(inv.id, D0)
        due = billed - paid
        if due <= 0:
            # payments already cover it; the status just wasn't updated
            continue
        age = (today - inv.date).days if inv.date else 0
        out.append({
            'id': inv.id,
            'invoice_number': inv.invoice_number or f'#{inv.id}',
            'date': inv.date.isoformat() if inv.date else None,
            'billed': billed,
            'paid': paid,
            'due': due,
            'age_days': age,
            'payment_status': inv.payment_status,
        })

    out.sort(key=lambda r: -r['age_days'])
    return out


def ageing(open_rows):
    """Bucket the outstanding balance by age. Reconciles to the total."""
    buckets = []
    for lo, hi in AGEING_BUCKETS:
        rows = [r for r in open_rows
                if r['age_days'] >= lo and (hi is None or r['age_days'] <= hi)]
        buckets.append({
            'label': bucket_label(lo, hi),
            'from_days': lo,
            'to_days': hi,
            'amount': sum((r['due'] for r in rows), D0),
            'count': len(rows),
        })
    return buckets


def payment_behaviour(invoices, payments, today=None):
    """How this party actually pays: speed, reliability, preferred method.

    "Days to pay" is measured from the invoice date to the *last* payment
    that settled it, so a part-payment followed by a final one counts as
    the full elapsed time rather than looking artificially prompt.
    """
    today = today or date.today()

    settled_on = {}          # invoice_id → latest payment date
    method_counts = {}
    for pay in payments:
        if pay.payment_method:
            method_counts[pay.payment_method] = method_counts.get(pay.payment_method, 0) + 1
        if pay.invoice_id and pay.date:
            prior = settled_on.get(pay.invoice_id)
            if prior is None or pay.date > prior:
                settled_on[pay.invoice_id] = pay.date

    spans = []
    for inv in invoices.filter(payment_status='paid'):
        done = settled_on.get(inv.id)
        if done and inv.date:
            spans.append((done - inv.date).days)

    invoice_dates = [i.date for i in invoices if i.date]
    payment_dates = [p.date for p in payments if p.date]

    return {
        'invoices_paid': len(spans),
        'avg_days_to_pay': round(sum(spans) / len(spans), 1) if spans else None,
        'slowest_days_to_pay': max(spans) if spans else None,
        'fastest_days_to_pay': min(spans) if spans else None,
        'preferred_method': (max(method_counts, key=method_counts.get)
                             if method_counts else None),
        'method_counts': method_counts,
        'last_invoice_date': max(invoice_dates).isoformat() if invoice_dates else None,
        'last_payment_date': max(payment_dates).isoformat() if payment_dates else None,
        'days_since_last_payment': ((today - max(payment_dates)).days
                                    if payment_dates else None),
    }


def monthly_activity(invoices, payments, months=6, today=None):
    """Billed vs collected per month — the shape of the relationship."""
    today = today or date.today()

    def shift(year, month, delta):
        idx = year * 12 + (month - 1) + delta
        return idx // 12, (idx % 12) + 1

    first_y, first_m = shift(today.year, today.month, -(months - 1))
    window_start = date(first_y, first_m, 1)

    billed, collected = {}, {}
    for inv in invoices:
        if inv.date and inv.date >= window_start:
            key = (inv.date.year, inv.date.month)
            billed[key] = billed.get(key, D0) + _d(inv.total_final_amount)
    for pay in payments:
        if pay.date and pay.date >= window_start:
            key = (pay.date.year, pay.date.month)
            collected[key] = collected.get(key, D0) + _d(pay.amount)

    out = []
    for i in range(months):
        y, m = shift(first_y, first_m, i)
        out.append({
            'label': date(y, m, 1).strftime('%b'),
            'month': f'{y}-{m:02d}',
            'billed': billed.get((y, m), D0),
            'collected': collected.get((y, m), D0),
        })
    return out


def lifetime_totals(entity_type, invoices, payments, notes):
    """All-time figures, so a 30-day window doesn't look like the whole story."""
    is_customer = entity_type == 'customer'
    billed = sum((_d(i.total_final_amount) for i in invoices), D0)
    gst = sum((_d(i.gst_final_amount) for i in invoices), D0)
    direction = 'received' if is_customer else 'made'
    settled = sum((_d(p.amount) for p in payments
                   if p.payment_type == direction), D0)
    return {
        'invoice_count': len(invoices) if isinstance(invoices, list) else invoices.count(),
        'billed': billed,
        'gst': gst,
        'settled': settled,
        'largest_invoice': max((_d(i.total_final_amount) for i in invoices), default=D0),
        'first_invoice_date': min((i.date for i in invoices if i.date), default=None),
    }


def month_end(day):
    return date(day.year, day.month, monthrange(day.year, day.month)[1])
