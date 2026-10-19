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
        raise ValueError('Enter a valid 15-character GST number, e.g. 29ABCDE1234F1Z5.')
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
