"""
Per-company configuration of the invoice header fields.

Each company chooses, for a handful of optional header fields, whether the
field is shown in the bill editor and whether a default value is filled in
when a new invoice is created. Showing and defaulting are independent: a
hidden field with a default still gets that default, which is the point for a
shop that always sells for cash and never wants to see "Payment method".

Defaults are applied on the server when an invoice is created (and only for
fields the client didn't send), so they hold for the web editor, the mobile
app and any other client alike. Nothing here rewrites an existing invoice.

Kept as plain functions with no Django imports so the rules are easy to test.
"""
import datetime

PAYMENT_STATUS_CHOICES = [
    ('unpaid', 'Unpaid'), ('partially_paid', 'Partially paid'),
    ('paid', 'Paid'), ('overdue', 'Overdue'),
]
PAYMENT_METHOD_CHOICES = [
    ('cash', 'Cash'), ('upi', 'UPI'), ('bank_transfer', 'Bank transfer'),
    ('cheque', 'Cheque'), ('card', 'Card'), ('other', 'Other'),
]
# Net-N shortcuts offered by the editor; 0 is "due on receipt".
TERMS_DAYS = (0, 7, 15, 30, 45, 60)
MAX_TEXT_LEN = 2000

# GSTIN state codes (see invoice_api.gst); duplicated as a tuple check here to
# keep this module free of imports.
def _valid_state_code(code):
    return isinstance(code, int) and ((1 <= code <= 38) or code in (97, 99))


CATALOG = [
    {'key': 'place_of_supply', 'label': 'Place of supply', 'type': 'state',
     'help': "Sales only. Left blank, GST uses the customer's state."},
    {'key': 'payment_terms', 'label': 'Payment terms and due date', 'type': 'terms',
     'options': [{'value': d, 'label': 'Due on receipt' if d == 0 else f'Net {d}'}
                 for d in TERMS_DAYS]},
    {'key': 'payment_status', 'label': 'Payment status', 'type': 'choice',
     'options': [{'value': v, 'label': l} for v, l in PAYMENT_STATUS_CHOICES]},
    {'key': 'payment_method', 'label': 'Payment method', 'type': 'choice',
     'options': [{'value': v, 'label': l} for v, l in PAYMENT_METHOD_CHOICES]},
    {'key': 'customer_notes', 'label': 'Notes', 'type': 'text'},
    {'key': 'terms', 'label': 'Terms and conditions', 'type': 'text'},
]
KEYS = [f['key'] for f in CATALOG]
_BY_KEY = {f['key']: f for f in CATALOG}

_EMPTY = ('', 'null', 'undefined', 'none')


def _blank():
    return {'visible': True, 'use_default': False, 'default': None}


def normalize(stored):
    """The full settings map, filling anything not stored with the defaults
    (everything shown, nothing defaulted) so an untouched company is unchanged."""
    stored = stored if isinstance(stored, dict) else {}
    out = {}
    for key in KEYS:
        entry = _blank()
        saved = stored.get(key)
        if isinstance(saved, dict):
            entry['visible'] = bool(saved.get('visible', True))
            entry['use_default'] = bool(saved.get('use_default', False))
            entry['default'] = saved.get('default')
        out[key] = entry
    return out


def _truthy(value):
    return value if isinstance(value, bool) else str(value).strip().lower() in ('true', '1', 'yes', 'on')


def _clean_default(key, value):
    """The validated default for a field, or raises ValueError with a message
    fit to show the user."""
    field = _BY_KEY[key]
    label = field['label']
    kind = field['type']

    if kind == 'state':
        try:
            code = int(value)
        except (TypeError, ValueError):
            raise ValueError(f'Choose a state for the {label.lower()} default.')
        if not _valid_state_code(code):
            raise ValueError('Choose a valid GST state.')
        return code

    if kind == 'terms':
        try:
            days = int(value)
        except (TypeError, ValueError):
            raise ValueError('Choose the payment terms to use by default.')
        if days not in TERMS_DAYS:
            raise ValueError('Unknown payment terms.')
        return days

    if kind == 'choice':
        allowed = [o['value'] for o in field['options']]
        if value not in allowed:
            raise ValueError(f'Choose a {label.lower()} to use by default.')
        return value

    text = str(value or '').strip()
    if not text:
        raise ValueError(f'Enter the default text for {label.lower()}, or turn the default off.')
    if len(text) > MAX_TEXT_LEN:
        raise ValueError(f'{label} can be at most {MAX_TEXT_LEN} characters.')
    return text


def validate(current, incoming):
    """Merge `incoming` over `current` and validate the result.

    Returns the normalized map to store. A partial update only changes the
    fields it names; an unknown field is an error rather than silently kept.
    Raises ValueError for the first problem found.
    """
    merged = normalize(current)
    if not isinstance(incoming, dict):
        raise ValueError('Send the fields as an object.')
    for key, patch in incoming.items():
        if key not in _BY_KEY:
            raise ValueError(f'Unknown field: {key}.')
        if not isinstance(patch, dict):
            raise ValueError(f'Settings for {key} must be an object.')
        entry = merged[key]
        if 'visible' in patch:
            entry['visible'] = _truthy(patch['visible'])
        if 'use_default' in patch:
            entry['use_default'] = _truthy(patch['use_default'])
        if 'default' in patch:
            entry['default'] = patch['default']

    for key, entry in merged.items():
        if entry['use_default']:
            entry['default'] = _clean_default(key, entry['default'])
        else:
            # keep what was typed so toggling the default back on restores it,
            # but only if it is itself valid
            try:
                entry['default'] = (_clean_default(key, entry['default'])
                                    if entry['default'] not in (None, '') else None)
            except ValueError:
                entry['default'] = None
    return merged


def _absent(data, key):
    if key not in data:
        return True
    value = data.get(key)
    return value is None or str(value).strip().lower() in _EMPTY


def _base_date(data, today):
    raw = data.get('date')
    try:
        return datetime.date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return today


def apply_defaults(data, settings, invoice_type='sales', today=None):
    """Fill the configured defaults into the data for a NEW invoice.

    Only fields the client left out are filled, so anything the user chose
    wins. `data` may be a dict or a QueryDict; a mutable copy is returned.
    """
    settings = normalize(settings)
    today = today or datetime.date.today()
    data = data.copy() if hasattr(data, 'copy') else dict(data)

    for key, entry in settings.items():
        if not entry['use_default'] or entry['default'] in (None, ''):
            continue
        if key == 'place_of_supply' and invoice_type == 'purchase':
            continue          # place of supply decides the tax on what you charge
        if key == 'payment_terms':
            if _absent(data, 'due_date'):
                due = _base_date(data, today) + datetime.timedelta(days=int(entry['default']))
                data['due_date'] = due.isoformat()
            continue
        if _absent(data, key):
            data[key] = entry['default']
    return data
