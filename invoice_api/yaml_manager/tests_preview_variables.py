"""
The template designer's PDF preview renders sample invoice data. Every
variable the designer offers must have a sample value there, otherwise the
preview shows a blank where the exported invoice would show text and the
designer can't tell whether the layout works.
"""
import io

from django.test import RequestFactory, SimpleTestCase

from yaml_manager.api.views import render_preview_response

try:
    from pypdf import PdfReader
except ImportError:                                        # pragma: no cover
    PdfReader = None

NEW_INVOICE_VARIABLES = [
    'invoice.due_date', 'invoice.place_of_supply', 'invoice.payment_status',
    'invoice.payment_method', 'invoice.notes', 'invoice.terms',
]


class PreviewVariableTests(SimpleTestCase):

    def render_text(self, variables):
        html = '<html><body>%s</body></html>' % ''.join(
            '<p>[%s]:{{ %s }}</p>' % (v, v) for v in variables)
        request = RequestFactory().get('/')
        request.user = type('Anon', (), {'user_company': None})()
        response = render_preview_response(request, html)
        pdf = b''.join(response.streaming_content)
        return PdfReader(io.BytesIO(pdf)).pages[0].extract_text()

    def test_new_invoice_variables_have_sample_values(self):
        if PdfReader is None:
            self.skipTest('pypdf is not installed')
        text = self.render_text(NEW_INVOICE_VARIABLES)
        for variable in NEW_INVOICE_VARIABLES:
            marker = '[%s]:' % variable
            self.assertIn(marker, text)
            value = text.split(marker, 1)[1].split('\n', 1)[0].strip()
            self.assertTrue(value, '%s rendered blank in the preview' % variable)
