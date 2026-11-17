"""GSTIN parsing and the state-code table used during company onboarding.

A GSTIN's first two digits are the state code, so a registered business never has to type its state. An
unregistered business still needs a state (invoices split CGST/SGST vs IGST on it), so it picks one by name.
"""
import re

STATE_CODES = {
    1: 'Jammu and Kashmir', 2: 'Himachal Pradesh', 3: 'Punjab', 4: 'Chandigarh', 5: 'Uttarakhand',
    6: 'Haryana', 7: 'Delhi', 8: 'Rajasthan', 9: 'Uttar Pradesh', 10: 'Bihar', 11: 'Sikkim',
    12: 'Arunachal Pradesh', 13: 'Nagaland', 14: 'Manipur', 15: 'Mizoram', 16: 'Tripura',
    17: 'Meghalaya', 18: 'Assam', 19: 'West Bengal', 20: 'Jharkhand', 21: 'Odisha', 22: 'Chhattisgarh',
    23: 'Madhya Pradesh', 24: 'Gujarat', 26: 'Dadra and Nagar Haveli and Daman and Diu',
    27: 'Maharashtra', 29: 'Karnataka', 30: 'Goa', 31: 'Lakshadweep', 32: 'Kerala', 33: 'Tamil Nadu',
    34: 'Puducherry', 35: 'Andaman and Nicobar Islands', 36: 'Telangana', 37: 'Andhra Pradesh',
    38: 'Ladakh', 97: 'Other Territory',
}

# 2 state digits, 10-char PAN, entity number, literal Z, check character.
GSTIN_RE = re.compile(r'^(\d{2})[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$')


def parse_gstin(value):
    """Return (normalised_gstin, state_code) or raise ValueError with a user-facing message."""
    gstin = re.sub(r'\s+', '', value or '').upper()
    match = GSTIN_RE.match(gstin)
    if not match:
        raise ValueError('Enter a valid 15-character GST number, e.g. 29ABCDE1234F1ZW.')
    code = int(match.group(1))
    if code not in STATE_CODES:
        raise ValueError('This GST number starts with an unknown state code.')
    return gstin, code


def state_code_for_name(name):
    wanted = re.sub(r'\s+', ' ', name or '').strip().lower().replace('&', 'and')
    for code, state in STATE_CODES.items():
        if state.lower() == wanted:
            return code
    return None


_GSTIN_CHARS = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'


def gstin_check_char(first14):
    """The 15th (check) character of a GSTIN, from its first 14 (mod-36 Luhn)."""
    total = 0
    for i, ch in enumerate(first14):
        v = _GSTIN_CHARS.index(ch) * (2 if i % 2 else 1)
        total += v // 36 + v % 36
    return _GSTIN_CHARS[(36 - total % 36) % 36]


def gstin_error(value):
    """User-facing reason a GSTIN is unusable on a return, or None if it's fine.

    Stricter than `parse_gstin`: also verifies the check character, which
    catches a single mistyped or swapped character that the pattern lets by.
    """
    try:
        gstin, _ = parse_gstin(value)
    except ValueError as e:
        return str(e)
    if gstin_check_char(gstin[:14]) != gstin[14]:
        return 'This GST number has a typo — its last character does not match the rest.'
    return None


def clean_party_gst(attrs, instance=None):
    """Validate a customer/vendor GSTIN and derive its state from it.

    Mutates and returns `attrs`. A blank GSTIN (unregistered party) leaves the
    state as given. A GSTIN that fails `gstin_error` raises ValueError with
    {'gst_number': message}; one whose state prefix contradicts an explicitly
    sent state code raises {'state_code': message}. Otherwise the state code and
    name are set from the GSTIN, which is where the party is registered.
    """
    if 'gst_number' not in attrs and not ({'state', 'state_code'} & set(attrs)):
        return attrs
    raw = attrs['gst_number'] if 'gst_number' in attrs else getattr(instance, 'gst_number', '')
    gst = re.sub(r'\s+', '', raw or '').upper()
    if 'gst_number' in attrs:
        attrs['gst_number'] = gst
    if not gst:
        return attrs
    err = gstin_error(gst)
    if err:
        raise ValueError({'gst_number': err})
    code = int(gst[:2])
    sent = attrs.get('state_code')
    if sent not in (None, '') and int(sent) != code:
        raise ValueError({'state_code': (
            f"This GST number is registered in {STATE_CODES[code]} ({code:02d}), "
            f"not state {int(sent):02d}. A business has a separate GST number in each state.")})
    attrs['state_code'] = code
    attrs['state'] = STATE_CODES[code]
    return attrs
