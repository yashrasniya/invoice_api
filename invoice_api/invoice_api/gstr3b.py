"""
GSTR-3B (monthly / quarterly summary return) and GSTR-9 (annual return)
figures, prepared from the books. Neither is filed from here: 3B is typed
into the portal, and GSTR-9 is a yearly reference.

Outward supplies come from the GSTR-1 builder's ledger (invoice_api.gstr1),
so 3B can't disagree with the GSTR-1 it sits next to. An invoice GSTR-1
couldn't classify is left out here too, and the issues say how many.

Inward supplies (purchases) are read here:

* input tax credit (Table 4) by kind: import of goods, import of services,
  inward reverse charge, everything else; then what's blocked (s.17(5), 4B(1))
  or reversed for now (4B(2)), per the purchase's or line's `itc_eligibility`;
* reverse-charge tax we owe (3.1(d)), always paid in cash;
* exempt, nil-rated and non-GST purchases (Table 5).

Credit needs a tax invoice from a registered supplier, so a taxed purchase
whose vendor has no GSTIN is left out of ITC and flagged (reverse charge
excepted: the recipient self-invoices).

Table 6.1 sets the credit off against the liability in the order Rule 88A
requires: IGST credit first (IGST, then CGST/SGST), CGST and SGST credit only
after it, and never against each other.
"""
from collections import OrderedDict
from decimal import Decimal

from accounts.gst_utils import gstin_error
from invoice_api.gst import STATE_NAMES, supply_type
from invoice_api.gstr1 import ZERO, _d, _heads, invoice_lines, money

HEADS = ('iamt', 'camt', 'samt')

OUTWARD_ROWS = OrderedDict([
    ('3.1a', 'Outward taxable supplies (other than zero-rated, nil-rated and exempted)'),
    ('3.1b', 'Outward taxable supplies (zero-rated: exports, SEZ)'),
    ('3.1c', 'Other outward supplies (nil-rated, exempted)'),
    ('3.1d', 'Inward supplies liable to reverse charge'),
    ('3.1e', 'Non-GST outward supplies'),
])
KIND_TO_31 = {'b2b': '3.1a', 'de': '3.1a', 'b2c': '3.1a', 'note': '3.1a',
              'exp_wp': '3.1b', 'exp_wop': '3.1b', 'sez_wp': '3.1b', 'sez_wop': '3.1b', 'note_zero': '3.1b',
              'nil': '3.1c', 'exempt': '3.1c', 'non_gst': '3.1e'}

ITC_ROWS = OrderedDict([
    ('4A1', 'Import of goods'),
    ('4A2', 'Import of services'),
    ('4A3', 'Inward supplies liable to reverse charge'),
    ('4A5', 'All other ITC'),
    ('4A', 'Total ITC available (4A)'),
    ('4B1', 'Reversed: blocked credit (s.17(5)) and rules 38, 42, 43'),
    ('4B2', 'Reversed: others (claimable later)'),
    ('4C', 'Net ITC available (4A − 4B)'),
])


def _row():
    return {'txval': ZERO, 'iamt': ZERO, 'camt': ZERO, 'samt': ZERO}


def _add(row, txval=ZERO, heads=None, sign=1):
    row['txval'] += sign * _d(txval)
    for h in HEADS:
        row[h] += sign * (heads or {}).get(h, ZERO)


def _out(row, **extra):
    return {**extra, 'taxable': money(row['txval']), 'igst': money(row['iamt']),
            'cgst': money(row['camt']), 'sgst': money(row['samt'])}


def set_off(liability, credit):
    """Use ITC against the liability per Rule 88A; returns (used, cash, left).

    `liability` and `credit` are {'igst','cgst','sgst'} Decimals. `used` is
    {(credit_head, liability_head): amount}. IGST credit goes first to IGST,
    then to CGST/SGST (where their own credit falls short first, so less cash
    is paid); CGST and SGST credit are used only after that, on their own
    head and then IGST, never on each other.
    """
    L = {h: max(_d(liability.get(h)), ZERO) for h in ('igst', 'cgst', 'sgst')}
    C = {h: max(_d(credit.get(h)), ZERO) for h in ('igst', 'cgst', 'sgst')}
    used = {}

    def use(src, dst, amount):
        if amount > 0:
            used[(src, dst)] = used.get((src, dst), ZERO) + amount
            L[dst] -= amount
            C[src] -= amount

    use('igst', 'igst', min(C['igst'], L['igst']))
    # what CGST/SGST credit can't cover gets IGST credit first, then the rest
    for h in ('cgst', 'sgst'):
        use('igst', h, min(C['igst'], max(L[h] - C[h], ZERO)))
    for h in ('cgst', 'sgst'):
        use('igst', h, min(C['igst'], L[h]))
    for h in ('cgst', 'sgst'):
        use(h, h, min(C[h], L[h]))
        use(h, 'igst', min(C[h], L['igst']))
    return used, L, C


class Gstr3b:
    """Build once from a GSTR-1 (same period) and the period's purchases."""

    def __init__(self, company, gstr1, purchases_qs, vendor_notes_qs):
        self.company, self.gstr1 = company, gstr1
        self.home = getattr(company, 'state_code', None)
        self.issues = []
        self.outward = OrderedDict((k, _row()) for k in OUTWARD_ROWS)
        self.buyer_rcm = _row()            # supplies where the buyer pays under reverse charge
        self.unreg = OrderedDict()         # 3.2: (buyer, pos) -> row
        self.itc = OrderedDict((k, _row()) for k in ITC_ROWS)
        self.rcm_itc = {'registered': _row(), 'unregistered': _row()}   # GSTR-9 6C / 6D
        self.inward_exempt = {'exempt': {'inter': ZERO, 'intra': ZERO}, 'non_gst': {'inter': ZERO, 'intra': ZERO}}
        self.counts = {'purchases': 0, 'purchases_left_out': 0}

        self._outward_from_ledger()
        # the company's own GSTIN / state problems apply to every return
        self.issues.extend(i for i in gstr1.issues if i['code'] in ('company_gstin', 'company_state_code'))
        if gstr1.flagged:
            left_out = f' ({gstr1.skipped} left out of these figures)' if gstr1.skipped else ''
            self._issue('error', 'gstr1_errors',
                        f'{gstr1.flagged} sales invoice(s) have GSTR-1 errors{left_out}, so these figures may be '
                        'wrong. Fix them on the GSTR-1 page first.')
        for inv in (purchases_qs.select_related('vendor', 'receiver')
                    .prefetch_related('products__product_properties__new_product_in_frontend')
                    .order_by('date', 'id')):
            self._add_purchase(inv)
        for note in vendor_notes_qs.select_related('vendor', 'invoice', 'invoice__vendor').order_by('date', 'id'):
            self._add_vendor_note(note)
        self._finish_itc()

    def _issue(self, level, code, message, invoice=None, note=None):
        ref = None
        if invoice is not None:
            ref = {'kind': 'invoice', 'id': invoice.id, 'number': invoice.invoice_number or '',
                   'date': invoice.date.isoformat() if invoice.date else ''}
        elif note is not None:
            ref = {'kind': 'note', 'id': note.id, 'number': note.note_number or '',
                   'date': note.date.isoformat() if note.date else ''}
        self.issues.append({'level': level, 'code': code, 'message': message, 'ref': ref})

    # ── outward ──

    def _outward_from_ledger(self):
        for e in self.gstr1.ledger:
            if e['kind'] == 'rcm_out':
                _add(self.buyer_rcm, e['txval'], e)
                continue
            key = KIND_TO_31[e['kind']]
            _add(self.outward[key], e['txval'], e)
            if key == '3.1a' and e['buyer'] and e['pos'] is not None:
                _add(self.unreg.setdefault((e['buyer'], e['pos']), _row()), e['txval'], e)

    # ── inward ──

    def _add_purchase(self, inv):
        self.counts['purchases'] += 1
        vendor = inv.vendor
        vgstin = (getattr(vendor, 'gst_number', '') or '').strip().upper()
        treatment = getattr(vendor, 'gst_treatment', '') or ('registered' if vgstin else 'unregistered')
        overseas = treatment == 'overseas'
        rcm = bool(inv.reverse_charge)
        supply = 'inter' if overseas else supply_type(inv, self.home)
        if supply is None:
            self.counts['purchases_left_out'] += 1
            self._issue('error', 'purchase_state',
                        "Can't tell IGST from CGST + SGST: set the vendor's state (or the bill's place of "
                        'supply). Left out.', invoice=inv)
            return
        if vgstin and gstin_error(vgstin):
            self._issue('warning', 'vendor_gstin',
                        f'Vendor GST number {vgstin} is not valid; credit may be refused.', invoice=inv)

        lines, _ = invoice_lines(inv)
        no_gstin_tax = ZERO
        for ln in lines:
            tax = _d(ln.tax)
            heads = _heads(tax, supply)
            eligibility = ln.itc or inv.itc_eligibility or 'eligible'
            service = (ln.hsn or '').startswith('99')
            if overseas:
                # imported services are taxed under reverse charge by law
                if service:
                    _add(self.outward['3.1d'], ln.txval, heads)
                row = '4A2' if service else '4A1'
            elif rcm:
                _add(self.outward['3.1d'], ln.txval, heads)
                _add(self.rcm_itc['registered' if vgstin else 'unregistered'], ln.txval, heads)
                row = '4A3'
            else:
                if treatment == 'composition' or (ln.rate == 0 and tax == 0):
                    col = 'non_gst' if ln.category == 'non_gst' else 'exempt'
                    self.inward_exempt[col][supply] += _d(ln.txval)
                    if tax and treatment == 'composition':
                        self._issue('warning', 'composition_tax',
                                    'A composition supplier can\'t charge GST, but this bill has some. '
                                    'It is not claimed as credit.', invoice=inv)
                    continue
                if not vgstin:
                    no_gstin_tax += tax
                    continue
                row = '4A5'
            _add(self.itc[row], ZERO, heads)
            if eligibility == 'blocked':
                _add(self.itc['4B1'], ZERO, heads)
            elif eligibility == 'reversal':
                _add(self.itc['4B2'], ZERO, heads)
        if no_gstin_tax:
            self._issue('warning', 'vendor_no_gstin',
                        f'{money(no_gstin_tax)} GST on this bill is not claimed: the vendor has no GST number, '
                        'and credit needs a tax invoice from a registered supplier.', invoice=inv)

    def _add_vendor_note(self, note):
        if note.gst_amount is None:
            self._issue('warning', 'note_gst_missing',
                        'Vendor credit/debit note has no GST amount, so ITC is not adjusted for it.', note=note)
            return
        vendor = note.vendor or (note.invoice.vendor if note.invoice_id else None)
        if note.invoice_id:
            supply = supply_type(note.invoice, self.home)
        else:
            origin = getattr(vendor, 'state_code', None)
            supply = None
            if origin and self.home:
                supply = 'intra' if int(origin) == int(self.home) else 'inter'
        if supply is None:
            self._issue('warning', 'purchase_state',
                        "Vendor note: can't tell IGST from CGST + SGST (no vendor state). Left out.", note=note)
            return
        sign = -1 if note.note_type == 'credit' else 1
        _add(self.itc['4A5'], ZERO, _heads(_d(note.gst_amount), supply), sign=sign)

    def _finish_itc(self):
        for k in ('4A1', '4A2', '4A3', '4A5'):
            _add(self.itc['4A'], ZERO, self.itc[k])
        _add(self.itc['4C'], ZERO, self.itc['4A'])
        _add(self.itc['4C'], ZERO, self.itc['4B1'], sign=-1)
        _add(self.itc['4C'], ZERO, self.itc['4B2'], sign=-1)

    # ── 6.1 ──

    def payment(self):
        liab = {'igst': ZERO, 'cgst': ZERO, 'sgst': ZERO}
        for key in ('3.1a', '3.1b'):
            for h, src in (('igst', 'iamt'), ('cgst', 'camt'), ('sgst', 'samt')):
                liab[h] += self.outward[key][src]
        net = self.itc['4C']
        credit = {'igst': net['iamt'], 'cgst': net['camt'], 'sgst': net['samt']}
        used, cash, left = set_off(liab, credit)
        rcm = self.outward['3.1d']
        rcm_cash = {'igst': rcm['iamt'], 'cgst': rcm['camt'], 'sgst': rcm['samt']}
        rows = []
        for h, label in (('igst', 'IGST'), ('cgst', 'CGST'), ('sgst', 'SGST')):
            rows.append({'head': label, 'liability': money(max(liab[h], ZERO)),
                         'paid_igst_credit': money(used.get(('igst', h), ZERO)),
                         'paid_cgst_credit': money(used.get(('cgst', h), ZERO)),
                         'paid_sgst_credit': money(used.get(('sgst', h), ZERO)),
                         'cash': money(cash[h]), 'reverse_charge_cash': money(rcm_cash[h])})
        return {
            'rows': rows,
            'cash_total': money(sum(cash.values(), ZERO) + sum(rcm_cash.values(), ZERO)),
            'credit_carried_forward': {h: money(v) for h, v in left.items()},
        }

    def summary(self):
        unreg = []
        for (buyer, pos), row in sorted(self.unreg.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            unreg.append({'buyer': 'composition' if buyer == 'comp' else 'unregistered',
                          'pos': f'{pos:02d}', 'state': STATE_NAMES.get(pos, str(pos)),
                          'taxable': money(row['txval']), 'igst': money(row['iamt'])})
        return {
            'outward': [_out(self.outward[k], key=k, label=label) for k, label in OUTWARD_ROWS.items()],
            'buyer_pays_reverse_charge': _out(self.buyer_rcm),
            'inter_state_unregistered': unreg,
            'itc': [_out(self.itc[k], key=k, label=label) for k, label in ITC_ROWS.items()],
            'inward_exempt': [
                {'label': 'Composition, exempt and nil-rated supplies',
                 'inter': money(self.inward_exempt['exempt']['inter']),
                 'intra': money(self.inward_exempt['exempt']['intra'])},
                {'label': 'Non-GST supplies',
                 'inter': money(self.inward_exempt['non_gst']['inter']),
                 'intra': money(self.inward_exempt['non_gst']['intra'])},
            ],
            'payment': self.payment(),
            'sales_counted': self.gstr1.counted,
            'sales_left_out': self.gstr1.skipped,
            'sales_with_errors': self.gstr1.flagged,
            'purchases_counted': self.counts['purchases'] - self.counts['purchases_left_out'],
            'purchases_left_out': self.counts['purchases_left_out'],
        }


# ── GSTR-9 ─────────────────────────────────────────────────────────────

def gstr9(gstr1, gstr3b):
    """GSTR-9 tables 4, 5, 6, 7 and 17 for a financial year, from the FY's
    GSTR-1 ledger and the FY's inward supplies (a Gstr3b built over the FY)."""
    t4 = OrderedDict((k, _row()) for k in ('4A', '4B', '4C', '4D', '4E', '4G', '4I', '4J', '4N'))
    t5 = OrderedDict((k, _row()) for k in ('5A', '5B', '5C', '5D', '5E', '5F', '5H', '5I', '5N'))
    kind4 = {'b2c': '4A', 'b2b': '4B', 'exp_wp': '4C', 'sez_wp': '4D', 'de': '4E'}
    kind5 = {'exp_wop': '5A', 'sez_wop': '5B', 'rcm_out': '5C', 'exempt': '5D', 'nil': '5E', 'non_gst': '5F'}
    for e in gstr1.ledger:
        k = e['kind']
        if k in kind4:
            _add(t4[kind4[k]], e['txval'], e)
        elif k in kind5:
            _add(t5[kind5[k]], e['txval'], e)
        elif k in ('note', 'note_zero'):
            taxed = k == 'note' or any(e[h] for h in HEADS)
            # amounts are signed (credit notes negative): report them positive
            row = (t4['4I'] if e['note'] == 'credit' else t4['4J']) if taxed else \
                  (t5['5H'] if e['note'] == 'credit' else t5['5I'])
            _add(row, -e['txval'] if e['note'] == 'credit' else e['txval'],
                 {h: (-e[h] if e['note'] == 'credit' else e[h]) for h in HEADS})
    _add(t4['4G'], gstr3b.outward['3.1d']['txval'], gstr3b.outward['3.1d'])
    for k in ('4A', '4B', '4C', '4D', '4E', '4G', '4J'):
        _add(t4['4N'], t4[k]['txval'], t4[k])
    _add(t4['4N'], t4['4I']['txval'], t4['4I'], sign=-1)
    for k in ('5A', '5B', '5C', '5D', '5E', '5F', '5I'):
        _add(t5['5N'], t5[k]['txval'], t5[k])
    _add(t5['5N'], t5['5H']['txval'], t5['5H'], sign=-1)

    itc = gstr3b.itc
    t6 = OrderedDict([
        ('6A', ('Total ITC availed through GSTR-3B (Table 4A)', itc['4A'])),
        ('6B', ('Inward supplies (other than imports and reverse charge)', itc['4A5'])),
        ('6C', ('Inward reverse charge from unregistered suppliers', gstr3b.rcm_itc['unregistered'])),
        ('6D', ('Inward reverse charge from registered suppliers', gstr3b.rcm_itc['registered'])),
        ('6E', ('Import of goods', itc['4A1'])),
        ('6F', ('Import of services', itc['4A2'])),
    ])
    t7 = OrderedDict([
        ('7E', ('Reversed: blocked credit (s.17(5))', itc['4B1'])),
        ('7H', ('Reversed: other reversals', itc['4B2'])),
    ])
    total7 = _row()
    for _, row in t7.values():
        _add(total7, ZERO, row)

    hsn = OrderedDict()
    for tab in ('b2b', 'b2c'):
        for (code, rate, uqc), r in gstr1.hsn[tab].items():
            row = hsn.setdefault((code, rate, uqc), {'desc': r['desc'], 'qty': ZERO, **_row()})
            row['qty'] += r['qty']
            _add(row, r['txval'], r)

    labels4 = {'4A': 'Supplies to unregistered persons (B2C)', '4B': 'Supplies to registered persons (B2B)',
               '4C': 'Exports with payment of tax', '4D': 'Supplies to SEZ with payment of tax',
               '4E': 'Deemed exports', '4G': 'Inward supplies on which you paid tax under reverse charge',
               '4I': 'Credit notes (−)', '4J': 'Debit notes (+)', '4N': 'Total'}
    labels5 = {'5A': 'Exports without payment of tax (LUT)', '5B': 'Supplies to SEZ without payment of tax',
               '5C': 'Supplies on which the buyer paid tax under reverse charge', '5D': 'Exempted',
               '5E': 'Nil-rated', '5F': 'Non-GST supplies', '5H': 'Credit notes (−)', '5I': 'Debit notes (+)',
               '5N': 'Total'}
    return {
        'table4': [_out(t4[k], key=k, label=labels4[k]) for k in t4],
        'table5': [_out(t5[k], key=k, label=labels5[k]) for k in t5],
        'table6': [_out(row, key=k, label=label) for k, (label, row) in t6.items()],
        'table7': [_out(row, key=k, label=label) for k, (label, row) in t7.items()]
                  + [_out(total7, key='7I', label='Total reversed')],
        # 7J: 6A less the reversals of table 7 (= 3B 4C summed over the year)
        'net_itc': _out(itc['4C'], key='7J', label='Net ITC available for use'),
        'table17': [{'hsn': code, 'desc': r['desc'], 'uqc': uqc, 'qty': float(r['qty']),
                     'rate': float(rate), 'taxable': money(r['txval']), 'igst': money(r['iamt']),
                     'cgst': money(r['camt']), 'sgst': money(r['samt'])}
                    for (code, rate, uqc), r in hsn.items()],
    }
