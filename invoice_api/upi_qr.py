"""UPI payment links and QR codes for invoices.

A company stores its UPI id (VPA) in its profile; when `show_upi_qr` is on,
every exported invoice carries a QR encoding a `upi://pay` deep link whose
`am` parameter is that invoice's grand total. Scanning it in any UPI app
opens a prepaid-amount payment to the company.

Two consumers, two shapes:
  * the HTML/WeasyPrint templates want a self-contained ``data:`` URI, since
    the PDF is rendered from a string with no server to fetch assets from;
  * the YAML/ReportLab templates want a PIL image handed straight to the
    canvas.
Both come from `build_upi_link` so the encoded payload can never drift
between the two export paths.
"""

import base64
import logging
import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from io import BytesIO
from urllib.parse import quote

logger = logging.getLogger(__name__)

# NPCI VPAs are <handle>@<psp>: the handle allows alphanumerics with dots,
# hyphens and underscores, the PSP suffix is letters only (okaxis, ybl, upi…).
UPI_ID_RE = re.compile(r'^[a-zA-Z0-9](?:[a-zA-Z0-9._-]{0,254})@[a-zA-Z][a-zA-Z0-9]{1,63}$')

# Sized for how the code is actually used: roughly a 100pt box on a PDF, which
# is ~208px at 150 DPI. box_size 4 lands a little above that, so the image is
# crisp when printed without carrying kilobytes of surplus pixels into every
# base64 data URI — and stays a sane size in a template that never sizes the
# <img> at all. The H error-correction level tolerates print smudging.
_QR_BOX_SIZE = 4
_QR_BORDER = 2


def is_valid_upi_id(upi_id):
    return bool(upi_id) and bool(UPI_ID_RE.match(str(upi_id).strip()))


def _format_amount(amount):
    """Return the amount as UPI's fixed 2-decimal string, or None if unusable.

    UPI rejects a malformed `am`, and an invoice total that is zero, negative
    or missing means "nothing to collect" — better to emit no QR at all than
    a QR that errors out inside the payer's bank app.
    """
    if amount is None:
        return None
    try:
        # HALF_UP, not Decimal's banker's-rounding default: a paise that
        # rounds down leaves the invoice short-paid.
        value = Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return None
    if value <= 0:
        return None
    return f"{value:.2f}"


def build_upi_link(upi_id, payee_name=None, amount=None, note=None):
    """Build a `upi://pay` deep link, or None when it could not be made valid."""
    if not is_valid_upi_id(upi_id):
        return None

    params = [('pa', str(upi_id).strip())]
    if payee_name:
        params.append(('pn', str(payee_name).strip()))

    formatted = _format_amount(amount)
    if formatted is None:
        return None
    params.append(('am', formatted))
    params.append(('cu', 'INR'))

    if note:
        # `tn` is capped at 50 chars by most PSPs; longer notes get rejected.
        params.append(('tn', str(note).strip()[:50]))

    query = '&'.join(f"{k}={quote(v, safe='')}" for k, v in params)
    return f"upi://pay?{query}"


def make_qr_image(link):
    """Render a link as a PIL image, or None if the QR library is unavailable."""
    if not link:
        return None
    try:
        import qrcode
        qr = qrcode.QRCode(
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=_QR_BOX_SIZE,
            border=_QR_BORDER,
        )
        qr.add_data(link)
        qr.make(fit=True)
        return qr.make_image(fill_color="black", back_color="white").convert("RGB")
    except Exception as e:
        logger.error(f"UPI QR generation failed: {e}")
        return None


def make_qr_data_uri(link):
    """Render a link as a base64 `data:image/png` URI for HTML templates."""
    img = make_qr_image(link)
    if img is None:
        return None
    try:
        buf = BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode('ascii')
    except Exception as e:
        logger.error(f"UPI QR encoding failed: {e}")
        return None


def company_upi_link(company, amount, note=None):
    """Build the UPI link for a company's invoice, honouring `show_upi_qr`.

    Returns None whenever the company has not opted in, has no usable UPI id,
    or the invoice has no positive total — every caller treats None as
    "render no QR" rather than as an error.
    """
    if company is None or not getattr(company, 'show_upi_qr', False):
        return None
    return build_upi_link(
        getattr(company, 'upi_id', None),
        payee_name=getattr(company, 'company_name', None),
        amount=amount,
        note=note,
    )
