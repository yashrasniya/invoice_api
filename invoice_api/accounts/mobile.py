import re


def normalize_mobile(mobile):
    """Digits (and a leading '+' for non-Indian numbers) with any +91 / 91 / leading-zero prefix removed."""
    if not mobile:
        return ""
    # Retain only digits and '+'
    mobile = "".join(c for c in str(mobile) if c.isdigit() or c == "+")

    # 1. Remove +91 prefix
    if mobile.startswith("+91"):
        mobile = mobile[3:]
    # 2. Remove 91 prefix if total length is > 10
    elif mobile.startswith("91") and len(mobile) > 10:
        mobile = mobile[2:]

    # 3. If more than 10 characters and starts with 0, remove the leading 0s
    while len(mobile) > 10 and mobile.startswith("0"):
        mobile = mobile[1:]

    return mobile


def clean_indian_mobile(value):
    """The 10 digit mobile number inside whatever the user typed ('+91 98765 43210', '098765-43210'), or None."""
    number = normalize_mobile(value)
    return number if re.fullmatch(r'[6-9]\d{9}', number) else None
