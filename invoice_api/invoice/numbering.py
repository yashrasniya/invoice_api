"""Per-company invoice number generation from a user-defined token template.

The grammar lives here and nowhere else: the settings API validates and previews
through these functions, and the create view generates through them, so the UI
can never preview a template the server would reject.

Sales and purchase invoices share one counter, but only sales invoices draw from
it (a purchase bill carries the vendor's own number) — that policy lives in the
view, not here.
"""
import logging
import re
from datetime import date

from django.utils import timezone

logger = logging.getLogger(__name__)

# Invoice.invoice_number is CharField(max_length=30)
MAX_RENDERED_LEN = 30

# CGST Rule 46(b) caps a tax invoice number at 16 characters. Advisory only —
# the API reports it as a warning and never blocks on it.
GST_RECOMMENDED_MAX_LEN = 16

DEFAULT_TEMPLATE = 'INV-{FY}-{SEQ:4}'

RESET_NEVER, RESET_MONTHLY, RESET_YEARLY, RESET_FY = 'never', 'monthly', 'yearly', 'fy'
RESET_CHOICES = [
    (RESET_NEVER, 'Never'),
    (RESET_MONTHLY, 'Every month'),
    (RESET_YEARLY, 'Every calendar year'),
    (RESET_FY, 'Every financial year (Apr-Mar)'),
]

# Served to the UI so its cheat-sheet cannot drift from what the parser accepts.
TOKEN_CATALOG = [
    {'token': '{YYYY}', 'label': 'Calendar year', 'example': '2026'},
    {'token': '{YY}', 'label': 'Calendar year, 2 digits', 'example': '26'},
    {'token': '{MM}', 'label': 'Month', 'example': '08'},
    {'token': '{DD}', 'label': 'Day', 'example': '23'},
    {'token': '{FY}', 'label': 'Financial year (Apr-Mar)', 'example': '2026-27'},
    {'token': '{FYS}', 'label': 'Financial year start', 'example': '2026'},
    {'token': '{FYE}', 'label': 'Financial year end', 'example': '2027'},
    {'token': '{SEQ}', 'label': 'Counter', 'example': '7'},
    {'token': '{SEQ:4}', 'label': 'Counter, zero-padded to 4', 'example': '0007'},
]

_TOKEN_RE = re.compile(r'\{([^{}]*)\}')
_VALID_TOKEN_RE = re.compile(r'^(YYYY|YY|MM|DD|FY|FYS|FYE|SEQ(:\d{1,2})?)$')
_SEQ_RE = re.compile(r'^SEQ(?::(\d{1,2}))?$')
# Literal text between tokens. Kept permissive (the GST subset is only advised);
# anything outside this set is almost certainly a typo'd brace.
_LITERAL_RE = re.compile(r'^[A-Za-z0-9 \-/_.#]*$')

MAX_TEMPLATE_LEN = 60
MAX_SEQ_PAD = 12


def fy_start_year(on_date):
    """Indian financial year: April to March. Same rule as invoice_api.gst."""
    return on_date.year if on_date.month >= 4 else on_date.year - 1


def period_key(reset_period, on_date):
    """The period the counter is currently counting inside.

    Keys are fixed-width within a reset_period, so a plain string compare
    orders them correctly.
    """
    if reset_period == RESET_MONTHLY:
        return on_date.strftime('%Y-%m')
    if reset_period == RESET_YEARLY:
        return on_date.strftime('%Y')
    if reset_period == RESET_FY:
        return 'FY%d' % fy_start_year(on_date)
    return ''


def _seq_pad(template):
    """Zero-padding width of the template's SEQ token, or 0 when unpadded."""
    for raw in _TOKEN_RE.findall(template):
        m = _SEQ_RE.match(raw)
        if m:
            return int(m.group(1)) if m.group(1) else 0
    return 0


def render(template, on_date, seq):
    """Render `template` for `on_date` and counter value `seq`.

    A sequence that outgrows its padding widens the number rather than being
    truncated — a wrong-but-unique number beats a silently colliding one.
    """
    fys = fy_start_year(on_date)
    values = {
        'YYYY': '%04d' % on_date.year,
        'YY': '%02d' % (on_date.year % 100),
        'MM': '%02d' % on_date.month,
        'DD': '%02d' % on_date.day,
        'FY': '%d-%02d' % (fys, (fys + 1) % 100),
        'FYS': '%04d' % fys,
        'FYE': '%04d' % (fys + 1),
    }

    def sub(match):
        raw = match.group(1)
        seq_match = _SEQ_RE.match(raw)
        if seq_match:
            pad = int(seq_match.group(1)) if seq_match.group(1) else 0
            return str(seq).zfill(pad)
        return values[raw]

    return _TOKEN_RE.sub(sub, template)


def validate_template(template, reset_period=RESET_NEVER):
    """Raise ValueError with a user-facing message if the template is unusable."""
    if not template or not template.strip():
        raise ValueError('Template cannot be empty.')
    if len(template) > MAX_TEMPLATE_LEN:
        raise ValueError('Template cannot be longer than %d characters.' % MAX_TEMPLATE_LEN)

    # Catch stray braces before the token scan, so '{SEQ' reports the real problem
    if template.count('{') != template.count('}'):
        raise ValueError('Unbalanced { } in the template.')

    tokens = _TOKEN_RE.findall(template)
    for raw in tokens:
        if not _VALID_TOKEN_RE.match(raw):
            raise ValueError("Unknown token '{%s}'." % raw)
        seq_match = _SEQ_RE.match(raw)
        if seq_match and seq_match.group(1) is not None:
            pad = int(seq_match.group(1))
            if not 1 <= pad <= MAX_SEQ_PAD:
                raise ValueError('{SEQ:n} padding must be between 1 and %d.' % MAX_SEQ_PAD)

    seq_count = sum(1 for raw in tokens if _SEQ_RE.match(raw))
    if seq_count != 1:
        raise ValueError('Template must contain exactly one {SEQ} token.')

    for literal in _TOKEN_RE.split(template)[::2]:
        if not _LITERAL_RE.match(literal):
            raise ValueError(
                'Only letters, digits, spaces and - / _ . # are allowed outside tokens.')

    # Must still fit the column once the counter outgrows its padding, not just today.
    pad = _seq_pad(template)
    probe = render(template, date(2026, 12, 31), 10 ** max(pad, 6) - 1)
    if len(probe) > MAX_RENDERED_LEN:
        raise ValueError(
            'Template renders to %d characters (e.g. "%s"); the maximum is %d.'
            % (len(probe), probe, MAX_RENDERED_LEN))

    # Resetting the counter without a matching period token in the number
    # produces literal duplicates, so this is an error rather than a warning.
    has_year = any(t in tokens for t in ('YYYY', 'YY'))
    has_fy = any(t in tokens for t in ('FY', 'FYS', 'FYE'))
    if reset_period == RESET_YEARLY and not (has_year or has_fy):
        raise ValueError(
            'Resetting every year needs a year token ({YYYY}, {YY} or {FY}) '
            'in the template, otherwise numbers repeat.')
    if reset_period == RESET_FY and not has_fy:
        raise ValueError(
            'Resetting every financial year needs {FY}, {FYS} or {FYE} '
            'in the template, otherwise numbers repeat.')
    if reset_period == RESET_MONTHLY and not ('MM' in tokens and (has_year or has_fy)):
        raise ValueError(
            'Resetting every month needs {MM} and a year token in the '
            'template, otherwise numbers repeat.')


def preview(template, reset_period=RESET_NEVER, seq=1, on_date=None):
    """Validate and render one example. Returns the UI's preview payload."""
    on_date = on_date or timezone.localdate()
    try:
        validate_template(template, reset_period)
    except ValueError as exc:
        return {'valid': False, 'error': str(exc)}
    rendered = render(template, on_date, seq)
    return {
        'valid': True,
        'preview': rendered,
        'length': len(rendered),
        'gst_warning': len(rendered) > GST_RECOMMENDED_MAX_LEN,
    }


def _reserve(cfg_pk, reset_period, on_date, *, cas_retries=10):
    """Claim the next counter value with a compare-and-swap.

    select_for_update() is a no-op on SQLite, so locking would buy nothing here.
    Instead the UPDATE carries the values we read as its WHERE clause: a caller
    that lost the race matches zero rows and retries. Correct on any backend.
    """
    from invoice.models import CompanyInvoiceNumbering

    key = period_key(reset_period, on_date)
    for _ in range(cas_retries):
        row = (CompanyInvoiceNumbering.objects.filter(pk=cfg_pk)
               .values('next_number', 'period_key').first())
        if row is None:
            return None
        stored = row['period_key']
        if key and stored and key > stored:
            seq, new_key = 1, key            # period rolled forward
        else:
            # Forward-only: a backdated generation never rewinds the series,
            # so an existing key is kept as-is. An empty stored key is adopted
            # without resetting, so switching reset_period on mid-series
            # doesn't restart at 1.
            seq, new_key = row['next_number'], (stored or key)

        updated = (CompanyInvoiceNumbering.objects
                   .filter(pk=cfg_pk,
                           next_number=row['next_number'],
                           period_key=stored)
                   .update(next_number=seq + 1, period_key=new_key))
        if updated:
            return seq
    logger.warning('numbering: CAS contention exhausted for config %s', cfg_pk)
    return None


def next_invoice_number(company, on_date=None, *, max_attempts=25):
    """Reserve and render the next invoice number for `company`.

    Returns the number, or None when numbering is off, misconfigured, or fails.
    Never raises: an unnumbered invoice is recoverable, a failed save is not.
    """
    if not company:
        return None
    on_date = on_date or timezone.localdate()
    try:
        from invoice.models import CompanyInvoiceNumbering, Invoice

        cfg = CompanyInvoiceNumbering.objects.filter(company=company).first()
        if cfg is None or not cfg.enabled:
            return None
        try:
            validate_template(cfg.template, cfg.reset_period)
        except ValueError as exc:
            logger.warning('numbering: company %s has an invalid template (%s)',
                           company.id, exc)
            return None

        for _ in range(max_attempts):
            seq = _reserve(cfg.pk, cfg.reset_period, on_date)
            if seq is None:
                return None
            candidate = render(cfg.template, on_date, seq)
            if len(candidate) > MAX_RENDERED_LEN:
                logger.error('numbering: company %s produced %r (>%d chars)',
                             company.id, candidate, MAX_RENDERED_LEN)
                return None
            # all_objects, not objects: a soft-deleted invoice still owns its
            # number, and handing it out twice would be a silent duplicate.
            taken = Invoice.all_objects.filter(
                user__user_company=company, invoice_number=candidate).exists()
            if not taken:
                return candidate
            # Collided with a manually typed or imported number — burn this
            # counter value and try the next one.
        logger.error('numbering: company %s exhausted %d attempts',
                     company.id, max_attempts)
        return None
    except Exception:
        logger.exception('numbering: unexpected failure for company %s',
                         getattr(company, 'id', None))
        return None
