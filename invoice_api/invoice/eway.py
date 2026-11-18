"""
E-way bills (rule 138, CGST Rules), Phase A: no API access.

What this module decides:

* **verdict**: whether an invoice's goods need an e-way bill. A hint shown
  to the user, never a block on saving the invoice.
* **validity**: how long a generated e-way bill lets the goods travel.
* **bill**: the invoice + its `EwayBill` row as one entry of the portal's
  bulk-upload JSON, or the issues that stop it from being one.

Like GSTR-1, anything the portal needs that the data can't supply is an
**issue** rather than a guess: `error` issues keep the invoice out of the
file, `warning` issues don't.

The file follows the e-way bill portal's bulk-generation format (the JSON
its offline tool produces: `version` + `billLists`). NIC publishes it as
an Excel/JSON template, not a formal schema: do one test upload on the
portal (ewaybillgst.gov.in → e-Waybill → Generate Bulk) before relying
on it. Rule figures below (₹50,000, 200 km a day, 180-day document age)
change by notification; check them against the portal's current advisories.

Phase A is outward supplies on our own sales invoices only. Delivery
challans (stock transfer, job work) and inward e-way bills come later.
"""
import math
import re
from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from accounts.gst_utils import STATE_CODES, gstin_check_char, gstin_error
from invoice_api.gst import FOREIGN_STATE_CODE, is_valid_state_code, supply_type
from invoice_api.gstr1 import DOC_NUMBER_RE, ZERO, _d, _heads, invoice_lines, money

IST = ZoneInfo('Asia/Kolkata')

#: Rule 138(1): an e-way bill is needed when the consignment value is
#: *more than* ₹50,000.
EWB_LIMIT = Decimal('50000')

#: States that set a higher limit for movement *within* the state, by GST
#: state code. Left empty on purpose: a wrong entry here would hide an e-way
#: bill that is actually required, while the ₹50,000 default can only
#: over-warn. Add a state only from its current notification.
INTRA_STATE_LIMITS = {}

#: The portal refuses to generate an e-way bill for a document older than
#: this (NIC advisory, from 1 Jan 2025).
MAX_DOC_AGE_DAYS = 180
MAX_DISTANCE_KM = 4000
#: Rule 138(10): one day of validity per 200 km (20 km for over-dimensional
#: cargo), or part of it.
KM_PER_DAY = {'R': 200, 'O': 20}

BULK_VERSION = '1.0.0621'

#: GST treatments whose GSTIN goes on the e-way bill as the recipient's.
REGISTERED_TREATMENTS = {'registered', 'composition', 'sez', 'deemed_export'}

# Indian registration plates as the portal accepts them, after removing
# spaces and hyphens: AB12C1234 / AB12CD1234 / AB121234 / ABC1234 (old),
# Bharat series 22BH1234AB, and temporary registrations TR/TM...
_VEHICLE_RES = [
    re.compile(r'^[A-Z]{2}\d{1,2}[A-Z]{0,3}\d{4}$'),
    re.compile(r'^[A-Z]{3}\d{4}$'),
    re.compile(r'^\d{2}BH\d{4}[A-Z]{1,2}$'),
    re.compile(r'^T[RM][A-Z0-9]{6,13}$'),
]
PIN_RE = re.compile(r'^[1-9]\d{5}$')
EWB_NUMBER_RE = re.compile(r'^\d{12}$')

# First two PIN digits → the states that PIN zone covers. Postal zones don't
# follow state lines exactly, so a mismatch is only a warning; the portal
# has the authoritative PIN table.
_PIN_STATES = {
    '11': {7}, '12': {6}, '13': {6, 3}, '14': {3}, '15': {3}, '16': {3, 4}, '17': {2},
    '18': {1}, '19': {1, 38},
    '20': {9}, '21': {9}, '22': {9}, '23': {9}, '24': {9, 5}, '25': {9}, '26': {9, 5},
    '27': {9}, '28': {9},
    '30': {8}, '31': {8}, '32': {8}, '33': {8}, '34': {8},
    '36': {24}, '37': {24}, '38': {24}, '39': {24, 26},
    '40': {27, 30}, '41': {27}, '42': {27}, '43': {27}, '44': {27},
    '45': {23}, '46': {23}, '47': {23}, '48': {23}, '49': {22},
    '50': {36, 37}, '51': {36, 37}, '52': {37}, '53': {37},
    '56': {29}, '57': {29}, '58': {29}, '59': {29},
    '60': {33, 34}, '61': {33}, '62': {33}, '63': {33}, '64': {33},
    '67': {32}, '68': {32, 31}, '69': {32},
    '70': {19}, '71': {19}, '72': {19}, '73': {19, 11}, '74': {19, 35},
    '75': {21}, '76': {21}, '77': {21},
    '78': {18}, '79': {12, 13, 14, 15, 16, 17, 18},
    '80': {10, 20}, '81': {10, 20}, '82': {10, 20}, '83': {20}, '84': {10}, '85': {10},
}


# ── small checks ───────────────────────────────────────────────────────

def normalize_vehicle(value):
    return re.sub(r'[\s-]+', '', str(value or '')).upper()


def vehicle_error(value):
    v = normalize_vehicle(value)
    if not v:
        return None
    if any(r.match(v) for r in _VEHICLE_RES):
        return None
    return f'"{value}" is not a vehicle number the portal accepts (e.g. KA01AB1234).'


def transporter_id_error(value):
    """Transporter GSTIN or TRANSIN: both are 15 characters ending in the
    same mod-36 check character."""
    v = re.sub(r'\s+', '', str(value or '')).upper()
    if not v:
        return None
    if not re.match(r'^\d{2}[0-9A-Z]{13}$', v):
        return 'A transporter ID is the 15-character GSTIN or TRANSIN of the transporter.'
    if gstin_check_char(v[:14]) != v[14]:
        return 'This transporter ID has a typo: its last character does not match the rest.'
    return None


def pin_matches_state(pin, state_code):
    """False only when the PIN zone clearly belongs to other states."""
    states = _PIN_STATES.get(str(pin or '')[:2])
    if not states or not state_code:
        return True
    try:
        return int(state_code) in states
    except (TypeError, ValueError):
        return True


def validity_until(generated_at, distance_km, vehicle_type='R'):
    """When an e-way bill generated at `generated_at` stops being valid.

    Each day of validity ends at the midnight after the day it starts, so a
    1-day e-way bill generated at 10:00 on the 5th runs to 23:59:59 on the 6th.
    None when the distance isn't known (0 = the portal works it out).
    """
    if not generated_at or not distance_km:
        return None
    per_day = KM_PER_DAY.get(vehicle_type, 200)
    days = max(1, math.ceil(int(distance_km) / per_day))
    local = generated_at.astimezone(IST) if generated_at.tzinfo else generated_at.replace(tzinfo=IST)
    last_day = local.date() + timedelta(days=days)
    return datetime.combine(last_day, time(23, 59, 59), tzinfo=IST)


# ── verdict ────────────────────────────────────────────────────────────

def is_goods(line):
    """Services carry a SAC (HSN chapter 99). A line with no code at all is
    treated as goods: missing it is reported, not assumed away."""
    return not (line.hsn or '').startswith('99')


def consignment_value(lines):
    """Rule 138 value: goods lines' taxable value plus tax, without exempt,
    nil-rated or non-GST goods (and without services)."""
    return sum((l.txval + l.tax for l in lines
                if is_goods(l) and l.category == 'taxable'), ZERO)


def verdict(invoice, company, lines=None):
    """{'needed', 'code', 'reason', 'consignment_value', 'limit'} for an invoice."""
    if lines is None:
        lines, _ = invoice_lines(invoice)
    value = consignment_value(lines)
    out = {'needed': False, 'consignment_value': money(value), 'limit': None}
    if invoice.invoice_type != 'sales':
        return {**out, 'code': 'purchase',
                'reason': 'Purchases: the supplier generates the e-way bill.'}
    if not any(is_goods(l) for l in lines):
        return {**out, 'code': 'services',
                'reason': 'Only services: no goods move, so no e-way bill.'}

    limit = EWB_LIMIT
    home = getattr(company, 'state_code', None)
    if supply_type(invoice, home) == 'intra' and home in INTRA_STATE_LIMITS:
        limit = INTRA_STATE_LIMITS[home]
    out['limit'] = money(limit)
    if value > limit:
        return {**out, 'needed': True, 'code': 'over_limit',
                'reason': f'Goods worth ₹{money(value):,.2f} are over the ₹{money(limit):,.0f} limit.'}
    return {**out, 'code': 'under_limit',
            'reason': f'Goods worth ₹{money(value):,.2f} are within the ₹{money(limit):,.0f} limit.'}


# ── defaults ───────────────────────────────────────────────────────────

def default_for(invoice):
    """An unsaved EwayBill with what can be worked out from the invoice."""
    from invoice.models import EwayBill
    party = invoice.receiver
    export = (getattr(party, 'gst_treatment', '') == 'overseas'
              or invoice.place_of_supply == FOREIGN_STATE_CODE)
    return EwayBill(invoice=invoice, sub_supply_type=3 if export else 1)


# ── the bulk-upload entry ──────────────────────────────────────────────

def _split_addr(text):
    text = re.sub(r'\s+', ' ', str(text or '')).strip()
    return text[:120], text[120:240]


def _date(d):
    return d.strftime('%d/%m/%Y') if d else ''


def _rate(value):
    r = Decimal(value or 0)
    return int(r) if r == r.to_integral_value() else float(r)


class Bill:
    """One invoice as an e-way bill entry.

    `issues` lists everything worth telling the user; `entry` is the
    `billLists` item, or None while any error remains.
    """

    def __init__(self, invoice, company, ewb=None, today=None):
        self.invoice, self.company = invoice, company
        self.ewb = ewb if ewb is not None else (getattr_safe(invoice, 'eway_bill') or default_for(invoice))
        self.today = today or datetime.now(IST).date()
        self.issues = []
        self.lines, self.line_problems = invoice_lines(invoice)
        self.verdict = verdict(invoice, company, self.lines)
        self.entry = self._build()

    @property
    def has_errors(self):
        return any(i['level'] == 'error' for i in self.issues)

    def _issue(self, level, code, message):
        if not any(i['code'] == code and i['message'] == message for i in self.issues):
            self.issues.append({'level': level, 'code': code, 'message': message})

    def _error(self, code, message):
        self._issue('error', code, message)

    def _warn(self, code, message):
        self._issue('warning', code, message)

    # parts ---------------------------------------------------------------

    def _check_document(self):
        inv, ewb = self.invoice, self.ewb
        if inv.invoice_type != 'sales':
            self._error('not_sales', 'E-way bills here are for your sales invoices only.')
        if ewb.status == 'generated' and ewb.ewb_number:
            self._error('already_generated',
                        f'Already has e-way bill {ewb.ewb_number}. Cancel it on the portal first '
                        'to make a new one.')
        if not DOC_NUMBER_RE.match(inv.invoice_number or ''):
            self._error('doc_number',
                        'The invoice number must be 1–16 letters, digits, "-" or "/" for the portal.')
        if inv.date and (self.today - inv.date).days > MAX_DOC_AGE_DAYS:
            self._error('doc_too_old',
                        f'The invoice is more than {MAX_DOC_AGE_DAYS} days old; the portal no longer '
                        'generates e-way bills for it.')
        if self.verdict['code'] == 'services':
            self._error('no_goods', self.verdict['reason'])
        elif self.verdict['code'] == 'under_limit':
            self._warn('under_limit', self.verdict['reason'] + ' An e-way bill is optional.')

    def _from_party(self):
        c = self.company
        gstin = (getattr(c, 'company_gst_number', '') or '').strip().upper()
        if not gstin:
            self._error('company_gstin', 'Add your GSTIN in company settings: e-way bills need it.')
        elif gstin_error(gstin):
            self._error('company_gstin', f'Your GSTIN: {gstin_error(gstin)}')
        state = getattr(c, 'state_code', None)
        if not is_valid_state_code(state) or int(state) in (FOREIGN_STATE_CODE, 99):
            self._error('company_state', 'Set your state in company settings.')
        pin = (getattr(c, 'pincode', '') or '').strip()
        if not PIN_RE.match(pin):
            self._error('company_pincode', 'Add your 6-digit PIN code in company settings '
                                           '(the dispatch-from PIN).')
        elif not pin_matches_state(pin, state):
            self._warn('company_pin_state', f'Your PIN code {pin} does not look like it is in '
                                            f'{STATE_CODES.get(state, "your state")}.')
        addr1, addr2 = _split_addr(getattr(c, 'company_address', ''))
        place = (getattr(c, 'city', '') or '').strip() or STATE_CODES.get(state, '')
        return {
            'userGstin': gstin, 'fromGstin': gstin,
            'fromTrdName': (getattr(c, 'company_name', '') or '')[:100],
            'fromAddr1': addr1, 'fromAddr2': addr2, 'fromPlace': place[:50],
            'fromPincode': int(pin) if PIN_RE.match(pin) else 0,
            'fromStateCode': int(state) if is_valid_state_code(state) else 0,
            'actualFromStateCode': int(state) if is_valid_state_code(state) else 0,
        }

    def _to_party(self):
        inv, ewb, party = self.invoice, self.ewb, self.invoice.receiver
        if party is None:
            self._error('no_customer', 'Pick a customer: the e-way bill needs who the goods go to.')
            return {}
        treatment = getattr(party, 'gst_treatment', '') or ''
        export = treatment == 'overseas' or ewb.sub_supply_type == 3
        gstin = (party.gst_number or '').strip().upper()
        if gstin and treatment in REGISTERED_TREATMENTS | {''}:
            if gstin_error(gstin):
                self._error('customer_gstin', f"{party.name}'s GSTIN: {gstin_error(gstin)}")
        else:
            gstin = 'URP'                    # unregistered person
        if export:
            gstin, bill_state = 'URP', 99    # other country
        else:
            bill_state = inv.place_of_supply or party.state_code
            if not is_valid_state_code(bill_state) or int(bill_state) == FOREIGN_STATE_CODE:
                self._error('customer_state', f"Set {party.name}'s state (or the invoice's place of supply).")

        ship_to = bool(ewb.ship_to_address or ewb.ship_to_pincode)
        if export and not ship_to:
            self._error('export_port', 'For an export, enter the port or airport the goods leave from '
                                       'as the ship-to address.')
        if ship_to:
            addr, place = ewb.ship_to_address, ewb.ship_to_place
            pin, state = (ewb.ship_to_pincode or '').strip(), ewb.ship_to_state_code
            who = 'the ship-to address'
        else:
            addr, place = party.address, party.city or party.district
            pin, state = (party.pincode or '').strip(), party.state_code
            who = f"{party.name}'s address"
        if not PIN_RE.match(pin):
            self._error('to_pincode', f'Add a 6-digit PIN code to {who}.')
        if not is_valid_state_code(state) or int(state) == FOREIGN_STATE_CODE:
            self._error('to_state', f'Set the state of {who}.')
        elif PIN_RE.match(pin) and not pin_matches_state(pin, state):
            self._warn('to_pin_state', f'PIN code {pin} does not look like it is in '
                                       f'{STATE_CODES.get(int(state), "that state")}.')
        addr1, addr2 = _split_addr(addr)
        return {
            'transType': 2 if ship_to else 1,
            'toGstin': gstin,
            # bill-to name; the bulk format has no separate ship-to name
            'toTrdName': (party.legal_name or party.name or '')[:100],
            'toAddr1': addr1, 'toAddr2': addr2,
            'toPlace': (place or STATE_CODES.get(state, '') or '')[:50],
            'toPincode': int(pin) if PIN_RE.match(pin) else 0,
            'toStateCode': int(bill_state) if is_valid_state_code(bill_state) else 0,
            'actualToStateCode': int(state) if is_valid_state_code(state) else 0,
        }

    def _items(self):
        home = getattr(self.company, 'state_code', None)
        supply = supply_type(self.invoice, home)
        if supply is None:
            self._error('supply_unknown', 'Set your state and the customer\'s state so CGST/SGST or IGST '
                                          'can be worked out.')
            supply = 'intra'
        for code, message in self.line_problems:
            if code in ('hsn_missing', 'hsn_invalid', 'rate_unknown'):
                self._error(code, message)
        goods = [l for l in self.lines if is_goods(l)]
        items, totals = [], {'txval': ZERO, 'camt': ZERO, 'samt': ZERO, 'iamt': ZERO}
        for n, line in enumerate(goods, 1):
            heads = _heads(line.tax, supply)
            rate = _d(line.rate)
            if line.qty <= 0:
                self._warn('qty_missing', 'A goods line has no quantity; the portal shows it as 0.')
            items.append({
                'itemNo': n,
                'productName': line.desc or 'Goods',
                'productDesc': line.desc or '',
                'hsnCode': int(line.hsn) if (line.hsn or '').isdigit() else 0,
                'quantity': float(line.qty),
                'qtyUnit': line.uqc if line.uqc and line.uqc != 'NA' else 'OTH',
                'taxableAmount': money(line.txval),
                'sgstRate': _rate(rate / 2) if supply == 'intra' else 0,
                'cgstRate': _rate(rate / 2) if supply == 'intra' else 0,
                'igstRate': _rate(rate) if supply == 'inter' else 0,
                'cessRate': 0,
                'cessNonAdvol': 0,
            })
            totals['txval'] += line.txval
            for k in ('camt', 'samt', 'iamt'):
                totals[k] += heads[k]
        if len(items) > 250:
            self._error('too_many_items', 'The portal takes at most 250 items on one e-way bill.')

        inv = self.invoice
        inv_total = _d(inv.total_final_amount) + (_d(inv.gst_final_amount) if inv.reverse_charge else ZERO)
        goods_total = totals['txval'] + totals['camt'] + totals['samt'] + totals['iamt']
        other = inv_total - goods_total
        if other < 0:
            # line totals above the invoice total (an invoice-level discount, or a
            # stale total); the portal wants the invoice value to cover the goods
            inv_total, other = goods_total, ZERO
        main_hsn = max(goods, key=lambda l: l.txval).hsn if goods else ''
        return {
            'totalValue': money(totals['txval']),
            'cgstValue': money(totals['camt']), 'sgstValue': money(totals['samt']),
            'igstValue': money(totals['iamt']), 'cessValue': 0, 'TotNonAdvolVal': 0,
            'OthValue': money(other), 'totInvValue': money(inv_total),
            'mainHsnCode': int(main_hsn) if (main_hsn or '').isdigit() else 0,
            'itemList': items,
        }

    def _transport(self):
        ewb = self.ewb
        if ewb.distance_km and ewb.distance_km > MAX_DISTANCE_KM:
            self._error('distance', f'Distance can be at most {MAX_DISTANCE_KM} km.')
        vehicle = normalize_vehicle(ewb.vehicle_number)
        trans_id = re.sub(r'\s+', '', ewb.transporter_id or '').upper()
        if transporter_id_error(trans_id):
            self._error('transporter_id', transporter_id_error(trans_id))
        if ewb.transport_mode == 1:
            if vehicle_error(vehicle):
                self._error('vehicle_number', vehicle_error(ewb.vehicle_number))
            if not vehicle and not trans_id:
                self._error('part_b', 'Add the vehicle number, or the transporter ID so the transporter '
                                      'can add the vehicle later.')
        else:
            if not (ewb.transport_doc_number and ewb.transport_doc_date) and not trans_id:
                self._error('part_b', 'For rail, air or ship, add the transport document number and date '
                                      '(RR / airway bill / bill of lading).')
        if ewb.transport_doc_date and self.invoice.date and ewb.transport_doc_date < self.invoice.date:
            self._error('trans_doc_date', 'The transport document date is before the invoice date.')
        return {
            'transMode': ewb.transport_mode,
            'transDistance': ewb.distance_km or 0,
            'transporterName': (ewb.transporter_name or '')[:100],
            'transporterId': trans_id,
            'transDocNo': (ewb.transport_doc_number or '')[:15],
            'transDocDate': _date(ewb.transport_doc_date),
            'vehicleNo': vehicle,
            'vehicleType': ewb.vehicle_type or 'R',
        }

    def _build(self):
        inv, ewb = self.invoice, self.ewb
        self._check_document()
        head = {
            'supplyType': ewb.supply_type or 'O',
            'subSupplyType': ewb.sub_supply_type or 1,
            'subSupplyDesc': '',
            'docType': ewb.doc_type or 'INV',
            'docNo': inv.invoice_number or '',
            'docDate': _date(inv.date),
        }
        head.update(self._from_party())
        head.update(self._to_party())
        head.update(self._items())
        head.update(self._transport())
        return None if self.has_errors else head


def getattr_safe(obj, name):
    try:
        return getattr(obj, name)
    except Exception:          # RelatedObjectDoesNotExist
        return None


def bulk_json(entries):
    """The file the portal's "Generate Bulk" page takes."""
    return {'version': BULK_VERSION, 'billLists': list(entries)}
