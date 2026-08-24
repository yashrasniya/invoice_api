"""Non-Latin text must survive both PDF back-ends.

The bug these cover: on a host with no font for a script, neither WeasyPrint
nor ReportLab draws a placeholder — the text is simply absent from the PDF, so
an invoice with a Hindi address exported looking complete while the address
line was blank. `only_latin_fonts` reproduces that host by pointing fontconfig
at a directory holding a single Latin-only face.
"""

import contextlib
import os
import re
import shutil
import tempfile
import unittest

from django.test import SimpleTestCase

import pdf_fonts

HINDI_ADDRESS = 'देहरादून रोड डोईवाला'

# One sample per bundled script, keyed by Script.key.
SAMPLES = {
    'devanagari': 'देहरादून रोड',
    'gujarati': 'અમદાવાદ ગુજરાત',
    'bengali': 'কলকাতা পশ্চিমবঙ্গ',
    'gurmukhi': 'ਲੁਧਿਆਣਾ ਪੰਜਾਬ',
    'tamil': 'சென்னை தமிழ்நாடு',
    'telugu': 'హైదరాబాద్ తెలంగాణ',
    'kannada': 'ಬೆಂಗಳೂರು ಕರ್ನಾಟಕ',
    'malayalam': 'കൊച്ചി കേരളം',
    'oriya': 'ଭୁବନେଶ୍ୱର ଓଡ଼ିଶା',
    'arabic': 'لاہور پنجاب',
    'korean': '서울특별시 강남구',
    'cjk': '上海市浦东新区',
}


class ScriptTableTest(SimpleTestCase):

    def test_every_script_has_its_font_files(self):
        missing = [f'{script.key}:{filename}'
                   for script in pdf_fonts.SCRIPTS
                   for filename in set(script.faces.values())
                   if not (pdf_fonts.FONT_DIR / filename).exists()]
        self.assertEqual(missing, [])

    def test_every_script_has_a_sample(self):
        self.assertEqual(sorted(SAMPLES),
                         sorted(script.key for script in pdf_fonts.SCRIPTS))

    def test_each_sample_is_detected_as_its_own_script(self):
        for key, text in SAMPLES.items():
            with self.subTest(script=key):
                scripts = {script.key for _, script in pdf_fonts.runs(text)
                           if script is not None}
                self.assertEqual(scripts, {key})

    def test_korean_is_matched_before_cjk(self):
        # Noto Sans SC has no Hangul, so 'cjk' claiming the shared ranges
        # first would send Korean to a font that cannot draw it.
        keys = [script.key for script in pdf_fonts.SCRIPTS]
        self.assertLess(keys.index('korean'), keys.index('cjk'))

    def test_ranges_cover_every_bundled_font(self):
        for script in pdf_fonts.SCRIPTS:
            with self.subTest(script=script.key):
                self.assertTrue(pdf_fonts.has_bundled_script(
                    SAMPLES[script.key]))


class DevanagariTextTest(SimpleTestCase):

    def test_detects_devanagari(self):
        self.assertTrue(pdf_fonts.has_devanagari(HINDI_ADDRESS))
        self.assertTrue(pdf_fonts.has_devanagari('Shop 4, ' + HINDI_ADDRESS))
        self.assertFalse(pdf_fonts.has_devanagari('Dehradun Road'))
        self.assertFalse(pdf_fonts.has_devanagari(SAMPLES['cjk']))
        self.assertFalse(pdf_fonts.has_devanagari(''))
        self.assertFalse(pdf_fonts.has_devanagari(None))

    def test_latin_needs_no_bundled_font(self):
        self.assertFalse(pdf_fonts.has_bundled_script('Dehradun 248140'))
        self.assertFalse(pdf_fonts.has_bundled_script(''))

    def test_runs_keep_scripts_apart(self):
        self.assertEqual(
            [(chunk, script.key if script else None) for chunk, script
             in pdf_fonts.runs('Shop 4, देहरादून रोड 上海 서울')],
            [('Shop 4, ', None), ('देहरादून रोड ', 'devanagari'),
             ('上海 ', 'cjk'), ('서울', 'korean')])

    def test_runs_of_pure_latin_is_a_single_chunk(self):
        self.assertEqual(pdf_fonts.runs('Dehradun 248140'),
                         [('Dehradun 248140', None)])

    def test_pre_base_matra_moves_ahead_of_its_cluster(self):
        # ि is typed after its consonant and printed before it. ReportLab does
        # no shaping, so without this the matra lands on the wrong side.
        devanagari = pdf_fonts.SCRIPTS[0]
        self.assertEqual(pdf_fonts.reorder('बिजनौर', devanagari), 'िबजनौर')
        self.assertEqual(pdf_fonts.reorder('दिल्ली', devanagari), 'िदल्ली')
        # a whole conjunct moves as one unit, not just the last consonant
        self.assertEqual(pdf_fonts.reorder('क्षि', devanagari), 'िक्ष')

    def test_reorder_leaves_other_text_alone(self):
        for text in (HINDI_ADDRESS, 'Dehradun Road', 'कुल राशी'):
            self.assertEqual(pdf_fonts.reorder(text), text)

    def test_scripts_without_verified_shaping_are_not_reordered(self):
        # Guessing at a reordering rule would produce confidently wrong text;
        # these scripts are left in logical order and flagged instead.
        for script in pdf_fonts.SCRIPTS:
            if script.prebase:
                continue
            with self.subTest(script=script.key):
                text = SAMPLES[script.key]
                self.assertEqual(pdf_fonts.reorder(text, script), text)


class FontCssInjectionTest(SimpleTestCase):

    def assert_injected(self, html):
        out = pdf_fonts.inject_font_css(html)
        self.assertIn('@font-face', out)
        self.assertIn('NotoSansDevanagari-Regular.ttf', out)
        return out

    def test_declares_every_bundled_family(self):
        css = pdf_fonts.font_face_css()
        for script in pdf_fonts.SCRIPTS:
            with self.subTest(script=script.key):
                self.assertIn(f"font-family: '{script.family}'", css)

    def test_declares_both_weights(self):
        css = pdf_fonts.font_face_css()
        self.assertIn('font-weight: normal', css)
        self.assertIn('font-weight: bold', css)

    def test_only_declares_the_scripts_present_in_the_text(self):
        # WeasyPrint hands every declared @font-face file to fontconfig
        # whether the page uses it or not, and the two CJK faces are 28MB
        # between them — declaring all of them put ~60ms on every invoice.
        self.assertEqual(pdf_fonts.font_face_css('Invoice 123'), '')

        hindi = pdf_fonts.font_face_css(HINDI_ADDRESS)
        self.assertEqual(hindi.count('@font-face'), 2)   # regular + bold
        self.assertIn('NotoSansDevanagari', hindi)
        self.assertNotIn('NotoSansSC', hindi)

        mixed = pdf_fonts.font_face_css(
            f"{HINDI_ADDRESS} {SAMPLES['cjk']} {SAMPLES['korean']}")
        for expected in ('NotoSansDevanagari', 'NotoSansSC', 'NotoSansKR'):
            self.assertIn(expected, mixed)

    def test_injection_declares_only_what_the_page_needs(self):
        page = ('<!DOCTYPE html><html><head></head><body>'
                f'<p>{HINDI_ADDRESS}</p></body></html>')
        out = pdf_fonts.inject_font_css(page)
        self.assertIn('NotoSansDevanagari', out)
        self.assertNotIn('NotoSansSC', out)

    def test_latin_only_page_is_returned_untouched(self):
        page = '<!DOCTYPE html><html><head></head><body><p>Total</p></body></html>'
        self.assertEqual(pdf_fonts.inject_font_css(page), page)

    def test_injects_at_end_of_head(self):
        out = self.assert_injected(
            '<!DOCTYPE html><html><head><meta charset="UTF-8">'
            f'</head><body>{HINDI_ADDRESS}</body></html>')
        # after the charset declaration, before </head>
        self.assertLess(out.index('charset'), out.index('@font-face'))
        self.assertLess(out.index('@font-face'), out.index('</head>'))

    def test_never_lands_before_the_doctype(self):
        # a <style> ahead of the doctype puts the document in quirks mode and
        # would silently relayout every existing template
        for html in (f'<!DOCTYPE html><html><body>{HINDI_ADDRESS}</body></html>',
                     f'<!DOCTYPE html><body>{HINDI_ADDRESS}</body>'):
            out = self.assert_injected(html)
            self.assertTrue(out.lower().startswith('<!doctype html>'), out[:40])

    def test_handles_a_bare_fragment(self):
        self.assert_injected(f'<div>{HINDI_ADDRESS}</div>')


@contextlib.contextmanager
def only_latin_fonts():
    """Run the block against a font set holding one Latin face.

    Yields the path of that face. It is "Latin" only by intent — macOS Arial
    also carries Arabic, for instance — so callers must check its coverage
    before asserting that a bundled font was the one that got used.
    """
    workdir = tempfile.mkdtemp()
    fontdir = os.path.join(workdir, 'fonts')
    os.makedirs(fontdir)
    # Any Latin-only face will do; the bundled Noto faces cover single
    # non-Latin scripts, so borrow a Latin one from the host and otherwise
    # skip — the point of the test is what is *absent*.
    latin = None
    for candidate in ('/System/Library/Fonts/Supplemental/Arial.ttf',
                      '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
        if os.path.exists(candidate):
            latin = candidate
            break
    if latin is None:
        shutil.rmtree(workdir, ignore_errors=True)
        raise unittest.SkipTest('no Latin-only font available to build a '
                                'restricted font set with')
    shutil.copy(latin, fontdir)
    cachedir = os.path.join(workdir, 'cache')
    os.makedirs(cachedir)
    conf = os.path.join(workdir, 'fonts.conf')
    with open(conf, 'w') as handle:
        handle.write(
            '<?xml version="1.0"?>'
            '<!DOCTYPE fontconfig SYSTEM "fonts.dtd"><fontconfig>'
            f'<dir>{fontdir}</dir><cachedir>{cachedir}</cachedir>'
            '</fontconfig>')
    previous = os.environ.get('FONTCONFIG_FILE')
    os.environ['FONTCONFIG_FILE'] = conf
    try:
        yield latin
    finally:
        if previous is None:
            os.environ.pop('FONTCONFIG_FILE', None)
        else:
            os.environ['FONTCONFIG_FILE'] = previous
        shutil.rmtree(workdir, ignore_errors=True)


class WeasyprintScriptTest(SimpleTestCase):
    """The HTML template back-end."""

    def page(self, text):
        return ('<!DOCTYPE html><html><head><meta charset="UTF-8"></head>'
                f'<body><p style="font-family:Arial,sans-serif">{text}</p>'
                '</body></html>')

    def embedded_fonts(self, pdf_bytes):
        return {name.split(b'+')[-1] for name in
                re.findall(rb'/BaseFont\s*/([-+A-Za-z0-9]+)', pdf_bytes)}

    def render(self, html):
        import weasyprint

        # uncompressed_pdf: font entries otherwise sit inside a compressed
        # object stream where /BaseFont cannot be grepped for.
        return weasyprint.HTML(string=html).write_pdf(uncompressed_pdf=True)

    def test_every_script_is_drawn_on_a_latin_only_host(self):
        from fontTools.ttLib import TTFont

        expected = {script.key: script.family.replace(' ', '-')
                    for script in pdf_fonts.SCRIPTS}
        with only_latin_fonts() as latin:
            host_cmap = set(TTFont(latin, lazy=True).getBestCmap())
            for key, text in SAMPLES.items():
                with self.subTest(script=key):
                    if all(ord(c) in host_cmap for c in text if c != ' '):
                        # The host face already covers this script (macOS
                        # Arial carries Arabic), so there is no fallback to
                        # observe and nothing this test can prove.
                        self.skipTest(f'host font already covers {key}')
                    page = self.page(text)
                    bare = self.embedded_fonts(self.render(page))
                    fixed = self.embedded_fonts(
                        self.render(pdf_fonts.inject_font_css(page)))
                    family = expected[key].encode()
                    # Nothing to draw it with, so it never reached the page.
                    self.assertNotIn(family, bare)
                    # The bundled face is embedded even though the paragraph
                    # asked for Arial: Pango falls back per script once the
                    # font is registered.
                    self.assertIn(family, fixed)


class ReportlabScriptTest(SimpleTestCase):
    """The YAML/coordinate template back-end."""

    def test_faces_register_lazily_for_every_script(self):
        for script in pdf_fonts.SCRIPTS:
            with self.subTest(script=script.key):
                self.assertIsNotNone(pdf_fonts.reportlab_font(script))
                self.assertIsNotNone(
                    pdf_fonts.reportlab_font(script, bold=True))

    def test_devanagari_font_covers_the_address(self):
        from reportlab.pdfbase import pdfmetrics

        pdf_fonts.register_reportlab_fonts()
        face = pdfmetrics.getFont('NotoSansDevanagari-Regular').face
        missing = [char for char in HINDI_ADDRESS
                   if char != ' ' and ord(char) not in face.charToGlyph]
        self.assertEqual(missing, [])

    def test_draw_text_keeps_latin_in_the_template_font(self):
        from reportlab.pdfgen import canvas

        from submit import Submit

        writer = Submit.__new__(Submit)
        writer.canvas_obj = canvas.Canvas('/dev/null')
        writer.canvas_obj.setFont('Times-Roman', 12)
        writer.draw_text(10, 10, 'Shop 4, ' + HINDI_ADDRESS)

        # the base font is restored, so the next field is unaffected
        self.assertEqual(writer.canvas_obj._fontname, 'Times-Roman')
        content = writer.canvas_obj.getpdfdata()
        self.assertIn(b'NotoSansDevanagari', content)
        self.assertIn(b'Times-Roman', content)

    def test_draw_text_switches_font_per_script_in_one_string(self):
        from reportlab.pdfgen import canvas

        from submit import Submit

        writer = Submit.__new__(Submit)
        writer.canvas_obj = canvas.Canvas('/dev/null')
        writer.canvas_obj.setFont('Times-Roman', 12)
        writer.draw_text(10, 10, f"{SAMPLES['devanagari']} "
                                 f"{SAMPLES['cjk']} {SAMPLES['korean']}")

        content = writer.canvas_obj.getpdfdata()
        for expected in (b'NotoSansDevanagari', b'NotoSansSC', b'NotoSansKR'):
            self.assertIn(expected, content)

    def test_unshaped_scripts_are_logged_not_silent(self):
        # Drawing beats dropping the line, but it must be diagnosable.
        pdf_fonts._shaping_warned.clear()
        unshaped = [s for s in pdf_fonts.SCRIPTS if not s.reportlab_ok]
        self.assertTrue(unshaped)
        with self.assertLogs('pdf_fonts', level='WARNING') as captured:
            for script in unshaped:
                pdf_fonts.warn_unshaped(script)
        self.assertEqual(len(captured.records), len(unshaped))
        self.assertIn('right-to-left', '\n'.join(captured.output))

        # and only once per process, so a 500-line invoice cannot flood the log
        with self.assertNoLogs('pdf_fonts', level='WARNING'):
            for script in unshaped:
                pdf_fonts.warn_unshaped(script)

    def test_shapeable_scripts_are_not_warned_about(self):
        pdf_fonts._shaping_warned.clear()
        with self.assertNoLogs('pdf_fonts', level='WARNING'):
            for script in pdf_fonts.SCRIPTS:
                if script.reportlab_ok:
                    pdf_fonts.warn_unshaped(script)
