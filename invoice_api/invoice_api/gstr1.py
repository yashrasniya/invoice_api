"""
GSTR-1 (statement of outward supplies) built from invoices and notes.

The output has two jobs:

* a **summary** a person can read: each table's count, taxable value and tax;
* a **portal JSON** (the GST offline tool / portal upload format) built from
  the same rows, so what is reviewed is exactly what is filed.

Everything the return needs that the data can't supply is reported as an
**issue** rather than guessed. `error` issues block the JSON download — a
return filed with a guessed rate, HSN or customer GSTIN is worse than one
filed a day late. `warning` issues are worth a look but don't block.

Tables built: 4A (B2B), 5 (B2CL), 6A (exports), 7 (B2CS), 8 (nil-rated),
9B (CDNR / CDNUR), 12 (HSN, split B2B / B2C) and 13 (documents issued).
Not modelled, so not produced: reverse charge, SEZ / deemed exports,
e-commerce (14/15), advances (11A/11B), amendments (9A/9C/10/11), cess.

GSTN publishes no formal JSON schema; field names follow the offline tool's
import format. Do one test upload on the portal before relying on it.
"""
import re
from collections import OrderedDict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from accounts.gst_utils import gstin_error
from invoice_api.gst import (FOREIGN_STATE_CODE, HSN_RE, VALID_GST_SLABS, is_gst_column,
                             is_hsn_column, is_valid_state_code, supply_type)

ZERO = Decimal('0')
CENT = Decimal('0.01')

#: Inter-state supplies to unregistered buyers above this invoice value are
#: reported invoice-wise in Table 5 (B2CL); at or below it, they are
#: aggregated in Table 7 (B2CS). ₹1 lakh since 1 Aug 2024 (was ₹2.5 lakh).
B2CL_LIMIT = Decimal('100000')

#: CGST Rule 46(b): an invoice/note number is at most 16 characters of
#: letters, digits, '-' and '/'.
DOC_NUMBER_RE = re.compile(r'^[A-Za-z0-9/-]{1,16}$')

# Line-item columns are company-configured free text; these are the titles
# read as each field (compared lower-case with non-letters removed).
_QTY_KEYS = {'quantity', 'qty', 'nos', 'pcs', 'quantitynos'}
_UNIT_KEYS = {'unit', 'units', 'uqc', 'uom'}
_DESC_KEYS = {'nameofproduct', 'product', 'productname', 'description', 'item', 'itemname',
              'particulars', 'goods', 'service', 'nameofitem'}


# Unit names people type → GSTN Unit Quantity Codes.
_UQC = {
    'nos': 'NOS', 'no': 'NOS', 'number': 'NOS', 'numbers': 'NOS', 'pc': 'PCS', 'pcs': 'PCS',
    'piece': 'PCS', 'pieces': 'PCS', 'kg': 'KGS', 'kgs': 'KGS', 'kilogram': 'KGS',
    'kilograms': 'KGS', 'g': 'GMS', 'gm': 'GMS', 'gms': 'GMS', 'gram': 'GMS', 'grams': 'GMS',
    'l': 'LTR', 'ltr': 'LTR', 'litre': 'LTR', 'liter': 'LTR', 'litres': 'LTR', 'ml': 'MLT',
    'm': 'MTR', 'mtr': 'MTR', 'meter': 'MTR', 'metre': 'MTR', 'box': 'BOX', 'boxes': 'BOX',
    'set': 'SET', 'sets': 'SET', 'pair': 'PRS', 'pairs': 'PRS', 'dozen': 'DOZ', 'doz': 'DOZ',
    'bag': 'BAG', 'bags': 'BAG', 'bottle': 'BTL', 'bottles': 'BTL', 'carton': 'CTN',
    'ctn': 'CTN', 'packet': 'PAC', 'pack': 'PAC', 'roll': 'ROL', 'rolls': 'ROL',
    'ton': 'TON', 'tonne': 'TON', 'sqft': 'SQF', 'sqm': 'SQM', 'unit': 'UNT', 'units': 'UNT',
    'quintal': 'QTL', 'qtl': 'QTL', 'na': 'NA', 'oth': 'OTH',
}
_VALID_UQC = set(_UQC.values())


def normalize_uqc(unit):
    """GSTN unit code for a typed unit ("kg", "Nos", "LTR"), or None if unknown."""
    raw = str(unit or '').strip()
    if not raw:
        return None
    return _UQC.get(re.sub(r'[^a-z]', '', raw.lower())) or (raw.upper() if raw.upper() in _VALID_UQC else None)


def _key(title):
    return re.sub(r'[^a-z]', '', str(title or '').lower())


def _d(value):
    try:
        return Decimal(str(value if value is not None else 0))
    except Exception:
        return ZERO


def money(value):
    """Amounts in the portal JSON: rupees to 2 decimals, as a float."""
    return float(_d(value).quantize(CENT, rounding=ROUND_HALF_UP))


def _rate_out(rate):
    r = _d(rate)
    return int(r) if r == r.to_integral_value() else float(r)


def _gst_date(d):
    return d.strftime('%d-%m-%Y') if d else ''


def _pos(code):
    return f'{int(code):02d}'


def snap_rate(taxable, tax):
    """The slab a (taxable, tax) pair was charged at, or None.

    Used only where a line has no GST-rate cell (header-only invoices, notes).
    Within ₹1 of a slab counts — the amounts were rounded per line — but no
    nearest-slab guessing beyond that.
    """
    taxable, tax = _d(taxable), _d(tax)
    if taxable <= 0:
        return Decimal('0') if tax == 0 else None
    for slab in VALID_GST_SLABS:
        if abs(taxable * slab / 100 - tax) <= Decimal('1'):
            return slab
    return None


# ── lines ──────────────────────────────────────────────────────────────

class Line:
    __slots__ = ('rate', 'txval', 'tax', 'hsn', 'desc', 'qty', 'uqc', 'hsn_column')

    def __init__(self, rate, txval, tax, hsn='', desc='', qty=ZERO, uqc='', hsn_column=False):
        self.rate, self.txval, self.tax = rate, txval, tax
        self.hsn, self.desc, self.qty, self.uqc = hsn, desc, qty, uqc
        # whether the line's columns include an HSN/SAC column at all
        self.hsn_column = hsn_column


def invoice_lines(invoice):
    """The invoice's lines as `Line`s, plus (code, message) problems.

    Line amounts come from the line's own columns (see invoice.line_calc).
    An invoice with no lines becomes one line from its header totals, which
    can be filed only if its rate is unambiguous — it can never carry an HSN.
    """
    from invoice.line_calc import calculate_line_detail

    problems = []
    lines = []
    products = list(invoice.products.all())
    if not products:
        txval = _d(invoice.total_final_amount) - _d(invoice.gst_final_amount)
        tax = _d(invoice.gst_final_amount)
        rate = snap_rate(txval, tax)
        if rate is None:
            problems.append(('rate_unknown', 'Has no line items and its GST does not match any GST rate.'))
        problems.append(('hsn_missing', 'Has no line items, so there is no HSN code to report.'))
        return [Line(rate, txval, tax)], problems

    for product in products:
        props = [(p.new_product_in_frontend, p.value) for p in product.product_properties.all()]
        detail = calculate_line_detail(props)
        if detail is not None:
            txval, tax, rate = detail['taxable'], detail['gst'], detail['rate']
            if rate is None:
                rate = Decimal('0')
        else:
            txval = _d(product.total_amount) - _d(product.gst_amount)
            tax = _d(product.gst_amount)
            rate = snap_rate(txval, tax)
            if rate is None:
                problems.append(('rate_unknown', "A line's GST does not match any GST rate."))
        if rate is not None and rate not in VALID_GST_SLABS:
            problems.append(('non_standard_rate', f'A line is taxed at {rate}%, which is not a GST rate.'))

        hsn = desc = unit = ''
        qty = ZERO
        for col, value in props:
            k, v = _key(col.input_title), str(value if value is not None else '').strip()
            if not v or is_gst_column(col.input_title):
                continue
            if is_hsn_column(col.input_title):
                hsn = re.sub(r'\s+', '', v)
            elif k in _QTY_KEYS:
                qty = _d(v) if re.match(r'^-?\d+(\.\d+)?$', v) else ZERO
            elif k in _UNIT_KEYS:
                unit = v
            elif k in _DESC_KEYS and not desc:
                desc = v
        if not desc:
            desc = next((str(v).strip() for c, v in props
                         if v and not c.is_calculable and not is_hsn_column(c.input_title)
                         and _key(c.input_title) not in _UNIT_KEYS), '')

        if not hsn:
            problems.append(('hsn_missing', 'A line has no HSN/SAC code.'))
        elif not HSN_RE.match(hsn):
            problems.append(('hsn_invalid', f'HSN/SAC "{hsn}" should be 4, 6 or 8 digits.'))

        uqc = normalize_uqc(unit) or ''
        if not uqc:
            # services are reported with no quantity; goods default to "Others"
            uqc = 'NA' if hsn.startswith('99') else 'OTH'
        lines.append(Line(rate, txval, tax, hsn, desc[:30], qty, uqc,
                          hsn_column=any(is_hsn_column(c.input_title) for c, _ in props)))
    return lines, problems


def _heads(tax, supply):
    tax = _d(tax)
    if supply == 'inter':
        return {'iamt': tax, 'camt': ZERO, 'samt': ZERO}
    half = (tax / 2).quantize(CENT, rounding=ROUND_HALF_UP)
    return {'iamt': ZERO, 'camt': half, 'samt': tax - half}


def _rate_items(lines, supply, igst_only=False):
    """Rate-wise items of one invoice (the portal wants one row per rate)."""
    by_rate = OrderedDict()
    for ln in lines:
        row = by_rate.setdefault(ln.rate, {'txval': ZERO, 'tax': ZERO})
        row['txval'] += ln.txval
        row['tax'] += ln.tax
    items = []
    for i, (rate, row) in enumerate(by_rate.items(), 1):
        heads = _heads(row['tax'], 'inter' if igst_only else supply)
        det = {'txval': money(row['txval']), 'rt': _rate_out(rate), 'iamt': money(heads['iamt'])}
        if not igst_only:
            det.update(camt=money(heads['camt']), samt=money(heads['samt']))
        det['csamt'] = 0
        items.append({'num': i, 'itm_det': det} if not igst_only else {**det})
    return items


# ── the return ─────────────────────────────────────────────────────────

class Gstr1:
    """Build once, read `summary()` / `portal_json()` / `issues`."""

    def __init__(self, company, sales_qs, notes_qs, start, end, deleted_sales_qs=None,
                 fy_numbers=None):
        self.company, self.start, self.end = company, start, end
        self.home = getattr(company, 'state_code', None)
        self.gstin = (getattr(company, 'company_gst_number', '') or '').strip().upper()
        self.issues = []
        self.b2b, self.b2cl, self.exp = OrderedDict(), OrderedDict(), {'WPAY': [], 'WOPAY': []}
        self.b2cs = OrderedDict()
        self.nil = {k: ZERO for k in ('INTRB2B', 'INTRAB2B', 'INTRB2C', 'INTRAB2C')}
        self.cdnr, self.cdnur = OrderedDict(), []
        self.hsn = {'b2b': OrderedDict(), 'b2c': OrderedDict()}
        self.totals = {k: {'count': 0, 'txval': ZERO, 'tax': ZERO}
                       for k in ('b2b', 'b2cl', 'b2cs', 'exp', 'nil', 'cdnr', 'cdnur')}

        self._check_company()
        sales = list(sales_qs.select_related('receiver')
                     .prefetch_related('products__product_properties__new_product_in_frontend')
                     .order_by('date', 'id'))
        self._check_numbers(sales, fy_numbers or [])
        self._saw_hsn_column = False
        for inv in sales:
            self._add_invoice(inv)
        self._collapse_missing_hsn_column()
        for note in notes_qs.select_related('customer', 'invoice').order_by('date', 'id'):
            self._add_note(note)
        self.doc_issue = self._documents(sales, deleted_sales_qs)

    # ── issues ──

    def _issue(self, level, code, message, invoice=None, note=None):
        ref = None
        if invoice is not None:
            ref = {'kind': 'invoice', 'id': invoice.id,
                   'number': invoice.invoice_number or '', 'date': invoice.date.isoformat() if invoice.date else ''}
        elif note is not None:
            ref = {'kind': 'note', 'id': note.id, 'number': note.note_number or '',
                   'date': note.date.isoformat() if note.date else ''}
        self.issues.append({'level': level, 'code': code, 'message': message, 'ref': ref})

    @property
    def has_errors(self):
        return any(i['level'] == 'error' for i in self.issues)

    def _check_company(self):
        if not self.gstin:
            self._issue('error', 'company_gstin', 'Your company has no GST number. GSTR-1 is filed against it.')
        else:
            err = gstin_error(self.gstin)
            if err:
                self._issue('error', 'company_gstin', f'Your company GST number {self.gstin} is not valid: {err}')
            elif is_valid_state_code(self.home) and int(self.gstin[:2]) != int(self.home):
                self._issue('error', 'company_state_code',
                            f'Your company state code ({self.home}) does not match your GST number, '
                            f'which is registered in state {self.gstin[:2]}.')
        if not is_valid_state_code(self.home):
            self._issue('error', 'company_state_code',
                        'Your company state code is missing or invalid, so supplies cannot be split '
                        'into intra-state and inter-state.')

    def _check_numbers(self, sales, fy_numbers):
        # uniqueness is per financial year: `fy_numbers` is (number, id) for
        # every sales invoice of the company in the period's FY
        seen = {}
        for number, inv_id in fy_numbers:
            if not number:
                continue
            seen.setdefault(number.strip().upper(), set()).add(inv_id)
        for inv in sales:
            num = (inv.invoice_number or '').strip()
            if not num:
                self._issue('error', 'invoice_number_missing', 'Invoice has no number.', invoice=inv)
            elif not DOC_NUMBER_RE.match(num):
                self._issue('error', 'invoice_number_format',
                            f'Invoice number "{num}" must be at most 16 letters, digits, "-" or "/".',
                            invoice=inv)
            if num and len(seen.get(num.upper(), ())) > 1:
                self._issue('error', 'invoice_number_duplicate',
                            f'Invoice number "{num}" is used more than once this financial year.',
                            invoice=inv)
            if inv.date and inv.date > date.today():
                self._issue('warning', 'future_dated', 'Invoice is dated in the future.', invoice=inv)

    # ── invoices ──

    def _collapse_missing_hsn_column(self):
        """No line has an HSN column at all: one fix (add the column), not one
        error per line."""
        if self._saw_hsn_column:
            return
        missing = [i for i in self.issues if i['code'] == 'hsn_missing']
        if not missing:
            return
        self.issues = [i for i in self.issues if i['code'] != 'hsn_missing']
        self._issue('error', 'no_hsn_column',
                    f'Your bill has no HSN/SAC column, so none of the {len(missing)} affected invoice(s) '
                    'can report HSN (Table 12). Add an "HSN" column in your bill fields, then fill it '
                    'in on these invoices.')

    def _add_invoice(self, inv):
        lines, problems = invoice_lines(inv)
        if any(ln.hsn_column for ln in lines):
            self._saw_hsn_column = True
        blocking = {'rate_unknown', 'hsn_missing', 'hsn_invalid', 'non_standard_rate'}
        for code, msg in dict.fromkeys(problems):        # de-dupe, keep order
            self._issue('error' if code in blocking else 'warning', code, msg, invoice=inv)
        if any(ln.rate is None for ln in lines):
            return

        customer = inv.receiver
        ctin = (getattr(customer, 'gst_number', '') or '').strip().upper()
        supply = supply_type(inv, self.home)
        pos = inv.place_of_supply or getattr(customer, 'state_code', None)
        value = _d(inv.total_final_amount)

        if ctin:
            err = gstin_error(ctin)
            if err:
                self._issue('error', 'customer_gstin',
                            f'Customer {customer.name}: GST number {ctin} is not valid — {err}', invoice=inv)
                return
            if ctin == self.gstin:
                self._issue('error', 'customer_gstin', 'Customer GST number is your own GST number.', invoice=inv)
                return
        if supply is None:
            self._issue('error', 'place_of_supply',
                        "Neither the invoice's place of supply nor the customer's state is set.", invoice=inv)
            return

        registered = bool(ctin)
        exporting = pos is not None and int(pos) == FOREIGN_STATE_CODE
        taxed = [ln for ln in lines if ln.rate > 0]
        nil = [ln for ln in lines if ln.rate == 0]

        # Table 8: nil-rated lines (exports report their 0% lines in 6A instead)
        if nil and not exporting:
            key = ('INTR' if supply == 'inter' else 'INTRA') + ('B2B' if registered else 'B2C')
            amt = sum((ln.txval for ln in nil), ZERO)
            self.nil[key] += amt
            self._tally('nil', amt, ZERO, count=0)

        self._hsn('b2b' if registered else 'b2c', lines, supply)

        if exporting:
            items = _rate_items(lines, 'inter', igst_only=True)
            typ = 'WPAY' if any(ln.tax > 0 for ln in lines) else 'WOPAY'
            self.exp[typ].append({'inum': inv.invoice_number, 'idt': _gst_date(inv.date),
                                  'val': money(value), 'itms': items})
            self._tally('exp', sum((ln.txval for ln in lines), ZERO), sum((ln.tax for ln in lines), ZERO))
            self._issue('warning', 'export_shipping_bill',
                        'Export invoice: add the shipping bill number, date and port code on the portal.',
                        invoice=inv)
            return
        if not taxed:
            return

        txval = sum((ln.txval for ln in taxed), ZERO)
        tax = sum((ln.tax for ln in taxed), ZERO)
        if registered:
            row = {'inum': inv.invoice_number, 'idt': _gst_date(inv.date), 'val': money(value),
                   'pos': _pos(pos), 'rchrg': 'N', 'inv_typ': 'R', 'itms': _rate_items(taxed, supply)}
            self.b2b.setdefault(ctin, []).append(row)
            self._tally('b2b', txval, tax)
        elif supply == 'inter' and value > B2CL_LIMIT:
            row = {'inum': inv.invoice_number, 'idt': _gst_date(inv.date), 'val': money(value),
                   'itms': _rate_items(taxed, 'inter', igst_only=False)}
            for it in row['itms']:            # B2CL rows carry IGST only
                it['itm_det'].pop('camt', None)
                it['itm_det'].pop('samt', None)
            self.b2cl.setdefault(_pos(pos), []).append(row)
            self._tally('b2cl', txval, tax)
        else:
            for ln in taxed:
                self._b2cs(supply, pos, ln.rate, ln.txval, ln.tax)
            self._tally('b2cs', txval, tax)

    def _b2cs(self, supply, pos, rate, txval, tax):
        key = ('INTER' if supply == 'inter' else 'INTRA', _pos(pos), rate)
        row = self.b2cs.setdefault(key, {'txval': ZERO, 'tax': ZERO})
        row['txval'] += txval
        row['tax'] += tax

    def _hsn(self, tab, lines, supply):
        for ln in lines:
            if not ln.hsn:
                continue
            key = (ln.hsn, ln.rate, ln.uqc)
            row = self.hsn[tab].setdefault(key, {'desc': ln.desc, 'qty': ZERO, 'txval': ZERO,
                                                 'iamt': ZERO, 'camt': ZERO, 'samt': ZERO})
            heads = _heads(ln.tax, supply)
            row['qty'] += ln.qty
            row['txval'] += ln.txval
            for h in ('iamt', 'camt', 'samt'):
                row[h] += heads[h]

    def _tally(self, table, txval, tax, count=1):
        t = self.totals[table]
        t['count'] += count
        t['txval'] += txval
        t['tax'] += tax

    # ── credit / debit notes ──

    def _add_note(self, note):
        num = (note.note_number or '').strip()
        if not num:
            self._issue('error', 'note_number_missing', 'Credit/debit note has no number.', note=note)
            return
        if not DOC_NUMBER_RE.match(num):
            self._issue('error', 'note_number_format',
                        f'Note number "{num}" must be at most 16 letters, digits, "-" or "/".', note=note)
        if note.gst_amount is None:
            self._issue('error', 'note_gst_missing', 'Credit/debit note has no GST amount recorded.', note=note)
            return
        txval = _d(note.amount) - _d(note.gst_amount)
        tax = _d(note.gst_amount)
        rate = snap_rate(txval, tax)
        if rate is None:
            self._issue('error', 'rate_unknown', "The note's GST does not match any GST rate.", note=note)
            return

        customer = note.customer or (note.invoice.receiver if note.invoice_id else None)
        inv = note.invoice
        pos = (inv.place_of_supply if inv else None) or getattr(customer, 'state_code', None)
        if not (is_valid_state_code(self.home) and is_valid_state_code(pos)):
            self._issue('error', 'place_of_supply', "The note's customer has no state set.", note=note)
            return
        supply = 'intra' if int(pos) == int(self.home) else 'inter'
        sign = -1 if note.note_type == 'credit' else 1
        ntty = 'C' if note.note_type == 'credit' else 'D'
        ctin = (getattr(customer, 'gst_number', '') or '').strip().upper()
        heads = _heads(tax, supply)
        det = {'txval': money(txval), 'rt': _rate_out(rate), 'iamt': money(heads['iamt']),
               'camt': money(heads['camt']), 'samt': money(heads['samt']), 'csamt': 0}
        base = {'ntty': ntty, 'nt_num': num, 'nt_dt': _gst_date(note.date), 'val': money(note.amount)}
        self._issue('warning', 'note_hsn',
                    'Notes have no line items, so Table 12 (HSN) is not adjusted for this note.', note=note)

        if ctin:
            err = gstin_error(ctin)
            if err:
                self._issue('error', 'customer_gstin', f'Customer GST number {ctin} is not valid — {err}', note=note)
                return
            self.cdnr.setdefault(ctin, []).append({**base, 'pos': _pos(pos), 'rchrg': 'N', 'inv_typ': 'R',
                                                   'itms': [{'num': 1, 'itm_det': det}]})
            self._tally('cdnr', sign * txval, sign * tax)
        elif int(pos) == FOREIGN_STATE_CODE:
            det = {k: v for k, v in det.items() if k not in ('camt', 'samt')}
            det['iamt'] = money(tax)
            self.cdnur.append({**base, 'typ': 'EXPWP' if tax > 0 else 'EXPWOP',
                               'itms': [{'num': 1, 'itm_det': det}]})
            self._tally('cdnur', sign * txval, sign * tax)
        elif supply == 'inter' and inv is not None and _d(inv.total_final_amount) > B2CL_LIMIT:
            det = {k: v for k, v in det.items() if k not in ('camt', 'samt')}
            self.cdnur.append({**base, 'typ': 'B2CL', 'pos': _pos(pos), 'itms': [{'num': 1, 'itm_det': det}]})
            self._tally('cdnur', sign * txval, sign * tax)
        else:
            # small B2C notes adjust Table 7 directly (negative for a credit note)
            self._b2cs(supply, pos, rate, sign * txval, sign * tax)
            self._tally('b2cs', sign * txval, sign * tax, count=0)

    # ── Table 13 ──

    def _documents(self, sales, deleted_qs):
        """Invoice series issued in the period: from / to / total / cancelled."""
        def series(number):
            m = re.match(r'^(.*?)(\d+)$', number)
            return (m.group(1), int(m.group(2))) if m else (number, None)

        groups = OrderedDict()
        for inv in sales:
            if inv.invoice_number:
                prefix, n = series(inv.invoice_number.strip())
                groups.setdefault(prefix, []).append((n, inv.invoice_number.strip(), False))
        for inv in (deleted_qs if deleted_qs is not None else []):
            if inv.invoice_number:
                prefix, n = series(inv.invoice_number.strip())
                groups.setdefault(prefix, []).append((n, inv.invoice_number.strip(), True))
        docs = []
        for i, (prefix, rows) in enumerate(groups.items(), 1):
            rows.sort(key=lambda r: (r[0] is None, r[0] or 0, r[1]))
            cancel = sum(1 for r in rows if r[2])
            docs.append({'num': i, 'from': rows[0][1], 'to': rows[-1][1],
                         'totnum': len(rows), 'cancel': cancel, 'net_issue': len(rows) - cancel})
        return docs

    # ── outputs ──

    def summary(self):
        tables = []
        labels = OrderedDict([
            ('b2b', '4A · B2B invoices'), ('b2cl', '5 · B2C large (inter-state > ₹1 lakh)'),
            ('exp', '6A · Exports'), ('b2cs', '7 · B2C others'), ('nil', '8 · Nil-rated'),
            ('cdnr', '9B · Credit/debit notes (registered)'),
            ('cdnur', '9B · Credit/debit notes (unregistered)'),
        ])
        for key, label in labels.items():
            t = self.totals[key]
            tables.append({'table': key, 'label': label, 'count': t['count'],
                           'taxable': money(t['txval']), 'tax': money(t['tax'])})
        hsn_rows = sum(len(v) for v in self.hsn.values())
        return {
            'tables': tables,
            'b2b_customers': len(self.b2b),
            'hsn_rows': hsn_rows,
            'documents': self.doc_issue,
            'total_taxable': money(sum((t['txval'] for t in self.totals.values()), ZERO)),
            'total_tax': money(sum((t['tax'] for t in self.totals.values()), ZERO)),
        }

    def portal_json(self):
        hsn = {}
        for tab in ('b2b', 'b2c'):
            rows = []
            for i, ((code, rate, uqc), r) in enumerate(self.hsn[tab].items(), 1):
                rows.append({'num': i, 'hsn_sc': code, 'desc': r['desc'], 'uqc': uqc,
                             'qty': float(r['qty']), 'rt': _rate_out(rate), 'txval': money(r['txval']),
                             'iamt': money(r['iamt']), 'camt': money(r['camt']),
                             'samt': money(r['samt']), 'csamt': 0})
            hsn[f'hsn_{tab}'] = rows

        b2cs = []
        for (sply, pos, rate), r in self.b2cs.items():
            heads = _heads(r['tax'], 'inter' if sply == 'INTER' else 'intra')
            row = {'sply_ty': sply, 'pos': pos, 'typ': 'OE', 'rt': _rate_out(rate),
                   'txval': money(r['txval']), 'iamt': money(heads['iamt']), 'csamt': 0}
            if sply == 'INTRA':
                row.update(camt=money(heads['camt']), samt=money(heads['samt']))
            b2cs.append(row)

        out = OrderedDict([
            ('gstin', self.gstin),
            ('fp', f'{self.end.month:02d}{self.end.year}'),
            ('b2b', [{'ctin': c, 'inv': invs} for c, invs in self.b2b.items()]),
            ('b2cl', [{'pos': p, 'inv': invs} for p, invs in self.b2cl.items()]),
            ('b2cs', b2cs),
            ('exp', [{'exp_typ': t, 'inv': invs} for t, invs in self.exp.items() if invs]),
            ('nil', {'inv': [{'sply_ty': k, 'nil_amt': money(v), 'expt_amt': 0, 'ngsup_amt': 0}
                             for k, v in self.nil.items() if v]}),
            ('cdnr', [{'ctin': c, 'nt': nts} for c, nts in self.cdnr.items()]),
            ('cdnur', self.cdnur),
            ('hsn', hsn),
            ('doc_issue', {'doc_det': [{'doc_num': 1, 'docs': self.doc_issue}]} if self.doc_issue else {}),
        ])
        # the offline tool rejects empty sections; leave them out
        return OrderedDict((k, v) for k, v in out.items()
                           if k in ('gstin', 'fp') or (v and (not isinstance(v, dict) or any(v.values()))))
