"""
The new invoice fields reach the template editors.

YAML templates are filled from InvoiceSerializerForPDF through FillValue, a
different path from the HTML templates, so each needs its own proof: a label
such as `due_date` or `notes` in a YAML header block must come out with the
invoice's value, in the same DD/MM/YYYY format as `date`.
"""
import datetime
from decimal import Decimal

from django.test import TestCase

from accounts.models import User
from invoice.models import Invoice
from invoice.serializers import InvoiceSerializerForPDF
from yaml_reader import FillValue, YamalReader

NEW_LABELS = ['due_date', 'place_of_supply', 'payment_status', 'payment_method', 'notes', 'terms']


def yaml_with_header_labels(labels):
    return {'Bill': {
        'harder': [{label: {'x': 10, 'y': 10 + i * 10, 'label': label}}
                   for i, label in enumerate(labels)],
        'footer': [],
        'product': {'product_list': []},
    }}


class TemplateFieldTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='seller', password='x12345678')
        self.invoice = Invoice.objects.create(
            user=self.user, invoice_number='INV-1', date=datetime.date(2026, 8, 10),
            due_date=datetime.date(2026, 8, 25), place_of_supply=27,
            payment_status='partially_paid', payment_method='upi',
            customer_notes='Thanks!', terms='Net 15',
            total_final_amount=Decimal('1180'), gst_final_amount=Decimal('180'))

    def test_serializer_prints_the_new_fields(self):
        data = InvoiceSerializerForPDF(self.invoice).data
        self.assertEqual(data['date'], '10/08/2026')
        self.assertEqual(data['due_date'], '25/08/2026')          # same format as date
        self.assertEqual(data['place_of_supply'], 'Maharashtra (27)')
        self.assertEqual(data['payment_status'], 'Partially Paid')
        self.assertEqual(data['payment_method'], 'UPI')
        self.assertEqual(data['notes'], 'Thanks!')
        self.assertEqual(data['terms'], 'Net 15')

    def test_unset_fields_print_as_empty_text_not_none(self):
        bare = Invoice.objects.create(user=self.user)
        data = InvoiceSerializerForPDF(bare).data
        for key in ('due_date', 'place_of_supply', 'payment_method', 'notes', 'terms'):
            self.assertEqual(data[key], '', key)

    def test_a_yaml_template_is_filled_with_the_new_fields(self):
        template = YamalReader(yaml_raw_data=yaml_with_header_labels(NEW_LABELS))
        fill = FillValue(InvoiceSerializerForPDF(self.invoice).data, template)
        values = {h.label: h.value for h in fill.headers}
        self.assertEqual(values['due_date'], '25/08/2026')
        self.assertEqual(values['place_of_supply'], 'Maharashtra (27)')
        self.assertEqual(values['payment_status'], 'Partially Paid')
        self.assertEqual(values['payment_method'], 'UPI')
        self.assertEqual(values['notes'], 'Thanks!')
        self.assertEqual(values['terms'], 'Net 15')
