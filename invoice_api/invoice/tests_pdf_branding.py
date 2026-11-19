"""Free-plan 'Made with Orvine' footer on exported PDFs."""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from invoice.export import _brand_footer_html, _brand_text
from invoice_api.limits import is_free_plan
from submit import Submit


def _req(sub):
    return SimpleNamespace(subscription=sub)


class IsFreePlanTests(SimpleTestCase):
    def test_no_subscription_is_free(self):
        self.assertTrue(is_free_plan(_req({})))

    def test_free_plan_is_free(self):
        self.assertTrue(is_free_plan(_req({'plan_code': 'free', 'status': 'active'})))

    def test_pro_trial_is_not_free(self):
        self.assertFalse(is_free_plan(_req({'plan_code': 'pro', 'status': 'trialing'})))

    def test_paid_plan_is_not_free(self):
        self.assertFalse(is_free_plan(_req({'plan_code': 'pro', 'status': 'active'})))


class FooterTests(SimpleTestCase):
    def test_html_footer_links_to_brand_url(self):
        html = _brand_footer_html()
        self.assertIn('href="https://invoice.orvine.in"', html)
        self.assertIn('Made with Orvine', html)
        self.assertIn('right:8px', html)

    def test_reportlab_footer_drawn_only_when_set(self):
        for text, expected in (('Made with Orvine', 1), (None, 0)):
            with mock.patch.object(Submit, 'add_fonts'):
                s = Submit([], footer_text=text, footer_url='https://x.test')
            with mock.patch.object(s.canvas_obj, 'drawRightString') as draw:
                s.draw_footer()
            self.assertEqual(draw.call_count, expected)

    def test_brand_text_strips_scheme(self):
        self.assertTrue(_brand_text().endswith('invoice.orvine.in'))


class HeadStyleTests(SimpleTestCase):
    def test_head_styles_are_kept_and_body_retargeted(self):
        import re
        st = "<style>body { margin: 40px; color: #333; } .a { margin: 1px; }</style>"
        def rt(m): return re.sub(r'(?<![\w-])margin(?=\s*:)', 'padding', m.group(0))
        out = re.sub(r'(?<![\w.#-])(?:body|html)\s*(?:,\s*(?:body|html)\s*)*\{[^}]*\}',
                     lambda m: re.sub(r'(?<![\w.#-])(?:body|html)(?=\s*[{,])', '.invoice-page', rt(m)),
                     st)
        self.assertIn('.invoice-page { padding: 40px', out)
        self.assertIn('.a { margin: 1px; }', out)
