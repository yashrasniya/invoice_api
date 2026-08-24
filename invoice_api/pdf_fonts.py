"""Non-Latin script support for both PDF back-ends.

A host with no font for a script does not fall back to a box or a question
mark — Pango and ReportLab both draw *nothing*, so an address like
"देहरादून रोड डोईवाला" silently vanished from the exported invoice while every
Latin field around it printed fine. Relying on whatever fonts the host happens
to ship is what made the output differ between a developer's Mac and the
deployed box, so the fonts live in `assets/fonts/` and are handed to both
renderers explicitly.

Two back-ends, two mechanisms:

* WeasyPrint (HTML templates) — `inject_font_css()` puts an ``@font-face``
  rule for every bundled family in the document. WeasyPrint registers each
  file with the fontconfig set it renders against, and Pango's per-script
  fallback then picks the right one even though the element asked for Arial.
  The template keeps its own typography for Latin text; only the characters
  no other font can draw come from here. The rules have to live in the HTML
  itself — passing the same CSS via ``write_pdf(stylesheets=…)`` registers
  nothing. Shaping is HarfBuzz's, so every script renders correctly.

* ReportLab (YAML/coordinate templates) — `runs()` splits a string by script
  so each stretch can be drawn with a font that has the glyphs. ReportLab does
  no OpenType shaping at all, so this makes the text *visible* but not always
  correctly ordered; see SCRIPTS below for which scripts that matters for.
  The HTML back-end is the right choice for anything but Latin and Devanagari.

Adding a script: drop the Noto face(s) in `assets/fonts/`, add a Script row,
and both back-ends pick it up.
"""

import logging
import re
from collections import namedtuple
from pathlib import Path

logger = logging.getLogger(__name__)

FONT_DIR = Path(__file__).resolve().parent / 'assets' / 'fonts'

Script = namedtuple('Script', 'key family ranges faces prebase reportlab_ok')
Script.__doc__ = """One writing system and the font that covers it.

key          short identifier, used in log messages and tests
family       CSS font-family name, also the ReportLab base font name
ranges       character-class body matching every codepoint of the script
faces        {'normal': filename, 'bold': filename} — one file may serve both
             (a variable font), in which case ReportLab gets its default
             instance and only WeasyPrint can vary the weight
prebase      matras typed after their consonant but printed before it, which
             ReportLab has to be told to move; '' when the script has none or
             when the reordering has not been verified
reportlab_ok True when the ReportLab back-end renders the script correctly,
             False when it can only make the text visible
"""


def _static(stem):
    return {'normal': f'{stem}-Regular.ttf', 'bold': f'{stem}-Bold.ttf'}


def _variable(stem):
    return {'normal': f'{stem}-VF.ttf', 'bold': f'{stem}-VF.ttf'}


SCRIPTS = (
    # Ranges are written as escapes on purpose: some of these blocks contain
    # characters with canonical decompositions (Devanagari क़ is क + nukta),
    # and a literal that gets normalised on the way into the file turns the
    # character class into a syntax error or, worse, a silently wrong range.
    #
    # Devanagari + Vedic Extensions + Devanagari Extended. Also covers
    # Marathi, Nepali, Sanskrit, Konkani and Maithili. Its pre-base matra
    # reordering is verified against HarfBuzz output, so this is the one
    # complex script the ReportLab back-end gets right.
    Script('devanagari', 'Noto Sans Devanagari',
           '\u0900-\u097f\u1cd0-\u1cff\ua8e0-\ua8ff',
           _static('NotoSansDevanagari'), '\u093f', True),
    Script('gujarati', 'Noto Sans Gujarati',
           '\u0a80-\u0aff', _static('NotoSansGujarati'), '', False),
    Script('bengali', 'Noto Sans Bengali',
           '\u0980-\u09ff', _static('NotoSansBengali'), '', False),
    Script('gurmukhi', 'Noto Sans Gurmukhi',
           '\u0a00-\u0a7f', _static('NotoSansGurmukhi'), '', False),
    Script('tamil', 'Noto Sans Tamil',
           '\u0b80-\u0bff', _static('NotoSansTamil'), '', False),
    Script('telugu', 'Noto Sans Telugu',
           '\u0c00-\u0c7f', _static('NotoSansTelugu'), '', False),
    Script('kannada', 'Noto Sans Kannada',
           '\u0c80-\u0cff', _static('NotoSansKannada'), '', False),
    Script('malayalam', 'Noto Sans Malayalam',
           '\u0d00-\u0d7f', _static('NotoSansMalayalam'), '', False),
    Script('oriya', 'Noto Sans Oriya',
           '\u0b00-\u0b7f', _static('NotoSansOriya'), '', False),
    # Arabic, Arabic Supplement, Arabic Extended-A and both Presentation
    # Forms blocks. Urdu lives here too. Needs contextual joining and
    # right-to-left layout, neither of which ReportLab does; WeasyPrint
    # handles both.
    Script('arabic', 'Noto Sans Arabic',
           '\u0600-\u06ff\u0750-\u077f\u08a0-\u08ff'
           '\ufb50-\ufdff\ufe70-\ufeff',
           _static('NotoSansArabic'), '', False),
    # Hangul Syllables, Jamo, Compatibility Jamo and both Jamo Extended
    # blocks. Matched before 'cjk' because Noto Sans SC covers the shared
    # punctuation but has no Hangul at all.
    Script('korean', 'Noto Sans KR',
           '\uac00-\ud7a3\u1100-\u11ff\u3130-\u318f'
           '\ua960-\ua97f\ud7b0-\ud7ff',
           _variable('NotoSansKR'), '', True),
    # One glyph per character and no reordering, so ReportLab handles CJK
    # correctly. Shipped as variable fonts: static instances come out no
    # smaller and would double the 28MB these two already cost.
    #
    # Noto Sans SC covers Simplified *and* Traditional Chinese plus Japanese
    # kana and kanji (99% of CJK Unified), which is why there is no separate
    # JP or TC face here.
    Script('cjk', 'Noto Sans SC',
           '\u2e80-\u2eff\u2f00-\u2fdf\u3000-\u303f'
           '\u3040-\u309f\u30a0-\u30ff\u3100-\u312f'
           '\u3190-\u319f\u31f0-\u31ff\u3400-\u4dbf'
           '\u4e00-\u9fff\uf900-\ufaff\ufe30-\ufe4f'
           '\uff00-\uffef',
           _variable('NotoSansSC'), '', True),
)

_MATCHERS = tuple((script, re.compile('[' + script.ranges + ']'))
                  for script in SCRIPTS)
_ANY_SCRIPT = re.compile(
    '[' + ''.join(script.ranges for script in SCRIPTS) + ']')

_CONSONANT = '\u0915-\u0939\u0958-\u095f\u0979-\u097f'
_NUKTA = '\u093c'
_VIRAMA = '\u094d'


def _prebase_pattern(matras):
    """Match a consonant cluster followed by one of `matras`."""
    return re.compile(
        '((?:[' + _CONSONANT + ']' + _NUKTA + '?' + _VIRAMA + ')*'
        '[' + _CONSONANT + ']' + _NUKTA + '?)([' + matras + '])')


_PREBASE = {script.key: _prebase_pattern(script.prebase)
            for script in SCRIPTS if script.prebase}

_script_cache = {}


def script_for(char):
    """The Script covering `char`, or None if a Latin font can draw it."""
    try:
        return _script_cache[char]
    except KeyError:
        pass
    found = None
    for script, matcher in _MATCHERS:
        if matcher.match(char):
            found = script
            break
    _script_cache[char] = found
    return found


def has_bundled_script(text):
    """True if `text` needs one of the bundled fonts to be visible at all."""
    return bool(text) and _ANY_SCRIPT.search(str(text)) is not None


def has_devanagari(text):
    """True if `text` contains Devanagari (Hindi, Marathi, Nepali, …)."""
    for script, matcher in _MATCHERS:
        if script.key == 'devanagari':
            return bool(text) and matcher.search(str(text)) is not None
    return False


def reorder(text, script=None):
    """Move pre-base matras ahead of their consonant, as a shaper would.

    Only scripts with a verified `prebase` are touched; everything else is
    returned unchanged rather than reordered on a guess.
    """
    key = script.key if script is not None else 'devanagari'
    pattern = _PREBASE.get(key)
    if pattern is None:
        return str(text)
    return pattern.sub(lambda m: m.group(2) + m.group(1), str(text))


def runs(text):
    """Split `text` into ``(chunk, script_or_None)`` pairs, in order.

    Whitespace joins whichever run precedes it, so "Shop 4, देहरादून रोड"
    yields two chunks rather than five and the space between the two Hindi
    words does not get measured in the Latin font.
    """
    grouped = []
    for char in str(text):
        script = script_for(char)
        if grouped and (grouped[-1][1] is script or char.isspace()):
            grouped[-1][0] += char
        else:
            grouped.append([char, script])
    return [(chunk, script) for chunk, script in grouped]


# --------------------------------------------------------------- weasyprint --

_rule_cache = {}


def _rules_for(script):
    """The ``@font-face`` rules for one script, built once."""
    try:
        return _rule_cache[script.key]
    except KeyError:
        pass
    rules = []
    for weight, filename in script.faces.items():
        path = FONT_DIR / filename
        if not path.exists():
            logger.warning("bundled font missing: %s", path)
            continue
        rules.append(
            "@font-face {{ font-family: '{family}'; font-weight: {weight};"
            " font-style: normal; src: url({url}); }}".format(
                family=script.family, weight=weight, url=path.as_uri()))
    _rule_cache[script.key] = rules
    return rules


def font_face_css(text=None):
    """``@font-face`` rules for the bundled faces, as a CSS string.

    With `text`, only the scripts that actually occur in it are declared.
    WeasyPrint hands every declared file to fontconfig whether the page uses
    it or not, and the two CJK faces are 28MB between them — declaring all of
    them unconditionally put ~60ms on the clock of every Hindi invoice.
    """
    rules = []
    for script, matcher in _MATCHERS:
        if text is not None and not matcher.search(text):
            continue
        rules.extend(_rules_for(script))
    return '\n'.join(rules)


_HEAD_END_RE = re.compile(r'</head\s*>', re.IGNORECASE)
_HEAD_RE = re.compile(r'<head[^>]*>', re.IGNORECASE)
_HTML_RE = re.compile(r'<html[^>]*>', re.IGNORECASE)
_DOCTYPE_RE = re.compile(r'<!doctype[^>]*>', re.IGNORECASE)
_BODY_RE = re.compile(r'<body[^>]*>', re.IGNORECASE)

def inject_font_css(html):
    """Return `html` with the bundled ``@font-face`` rules added to its head.

    Callers pass anything from a full document to a bare fragment, so the
    block goes at the first position that keeps the markup valid. It is never
    prepended ahead of a doctype — that would drop the document into quirks
    mode and change the layout of every existing template — and the closing
    ``</head>`` is preferred over the opening tag so that nothing already in
    the head, ``<meta charset>`` in particular, gets pushed further down.
    """
    css = font_face_css(html)
    if not css:
        return html
    block = '<style>\n{}\n</style>'.format(css)

    match = _HEAD_END_RE.search(html)
    if match:
        return html[:match.start()] + block + html[match.start():]

    for pattern, wrap in ((_HEAD_RE, '{}'),
                          (_HTML_RE, '<head>{}</head>'),
                          (_DOCTYPE_RE, '{}')):
        match = pattern.search(html)
        if match:
            at = match.end()
            return html[:at] + wrap.format(block) + html[at:]

    match = _BODY_RE.search(html)
    if match:
        return html[:match.start()] + block + html[match.start():]
    return block + html


# ---------------------------------------------------------------- reportlab --

# script key -> {weight: reportlab font name or None if it could not load}
_reportlab_registered = {}
_shaping_warned = set()


def warn_unshaped(script):
    """Log once per process when ReportLab is asked for a script it mangles.

    The text is still drawn — a missing address line is worse than a
    misplaced vowel sign — but this is the only signal that the invoice needs
    an HTML template to come out right, so it should not be silent.
    """
    if script.reportlab_ok or script.key in _shaping_warned:
        return
    _shaping_warned.add(script.key)
    logger.warning(
        "%s text drawn by the ReportLab back-end, which does no OpenType "
        "shaping: vowel signs may sit in the wrong place%s. Use an HTML "
        "template for this language to get correct output.",
        script.key,
        " and the text will not be joined or right-to-left"
        if script.key == 'arabic' else "")


def reportlab_font(script, bold=False):
    """Register `script`'s face on first use and return its ReportLab name.

    Registration is lazy and per script: eagerly loading all of them would
    make every invoice pay for parsing 30MB of CJK outlines that a Hindi
    address does not need. Returns None if the face cannot be loaded, in
    which case the caller should fall back to drawing with the base font.
    """
    weight = 'bold' if bold else 'normal'
    faces = _reportlab_registered.setdefault(script.key, {})
    if weight in faces:
        return faces[weight]

    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    filename = script.faces[weight]
    # A variable font serves both weights from one file, so ReportLab sees a
    # single face and bold text renders at regular weight.
    name = Path(filename).stem
    path = FONT_DIR / filename
    if not path.exists():
        logger.warning("bundled font missing: %s", path)
        faces[weight] = None
        return None
    try:
        pdfmetrics.registerFont(TTFont(name, str(path)))
    except Exception as exc:
        # A missing or unreadable font must not take the whole export down;
        # that text stays invisible, everything else prints.
        logger.error("could not register %s: %s", name, exc)
        faces[weight] = None
        return None
    faces[weight] = name
    return name


def register_reportlab_fonts():
    """Eagerly register the Devanagari faces.

    Kept for the common case — an Indian invoice whose only non-Latin text is
    Hindi — so the first `draw_text` does not pay for it. Every other script
    is registered on demand by `reportlab_font`.
    """
    for script in SCRIPTS:
        if script.key == 'devanagari':
            reportlab_font(script)
            reportlab_font(script, bold=True)
            return
