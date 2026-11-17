"""
Regression tests for four GST bugs:

1. PDFs always printed CGST + SGST, even on an inter-state invoice (IGST).
2. Line and invoice tax were stored exactly as the client sent them; a GST
   column titled anything but "GST" was multiplied into the line total.
3. Place of supply 96 (Other Countries, i.e. exports) was rejected, so every
   export invoice landed in "unclassified".
4. Credit/debit notes never moved the GST liability.
"""
import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from accounts.authz_seed import ensure_company_roles
from accounts.models import CompanyPermission, CompanyRole, UserCompanies
from companies.models import Customers, Vendor
from invoice.line_calc import calculate_line
from invoice.models import CreditDebitNote, Invoice, new_product_in_frontend
from invoice.serializers import InvoiceSerializerForPDF
from invoice.tests_numbering import give_plan
from invoice_api.gst import (adapt_html_for_igst, gst_rate_error, is_gst_column,
                             is_valid_state_code, note_totals, supply_type, tax_heads)
from yaml_reader import FillValue, YamalReader

User = get_user_model()


# ── 1. CGST/SGST vs IGST on the printed invoice ────────────────────────────

class TaxHeadTests(SimpleTestCase):

    def test_inter_state_is_igst_only(self):
        t = tax_heads(1000, 180, 'inter')
        self.assertEqual((t['center_gst_amount'], t['state_gst_amount'], t['igst_amount']), (0, 0, 180))
        self.assertEqual((t['igst'], t['center_gst'], t['state_gst']), (18, 0, 0))

    def test_intra_state_halves_and_sums_exactly(self):
        t = tax_heads(100, 0.05, 'intra')
        self.assertEqual(t['igst_amount'], 0)
        self.assertAlmostEqual(t['center_gst_amount'] + t['state_gst_amount'], 0.05)

    def test_unknown_supply_keeps_the_old_halves(self):
        t = tax_heads(1000, 180, None)
        self.assertEqual((t['center_gst_amount'], t['state_gst_amount'], t['igst_amount']), (90, 90, 0))

    def test_cgst_sgst_only_template_is_relabelled(self):
        html = ('<td>CGST Amount : {{ footer.center_gst_amount }}/-</td>'
                '<td>SGST Amount : {{ footer.state_gst_amount }}/-</td>'
                '<div>CGST {{ footer.center_gst }} %</div><div>SGST {{ footer.state_gst }} %</div>')
        out = adapt_html_for_igst(html)
        self.assertIn('IGST Amount : {{ footer.igst_amount }}/-', out)
        self.assertIn('IGST {{ footer.igst }} %', out)
        self.assertNotIn('SGST', out)
        self.assertNotIn('CGST', out)

    def test_template_with_an_igst_slot_is_untouched(self):
        html = '<td>CGST {{ footer.center_gst }}</td><td>IGST {{ igst }}</td>'
        self.assertEqual(adapt_html_for_igst(html), html)


class SupplyTypeTests(TestCase):

    def setUp(self):
        self.company = UserCompanies.objects.create(company_name='Seller', state_code=29)
        self.user = User.objects.create_user(username='s', password='x12345678')
        self.user.user_company = self.company
        self.user.save()
        self.mh = Customers.objects.create(user=self.user, name='MH buyer', state_code=27)
        self.ka = Customers.objects.create(user=self.user, name='KA buyer', state_code=29)

    def invoice(self, **kw):
        kw.setdefault('total_final_amount', Decimal('1180'))
        kw.setdefault('gst_final_amount', Decimal('180'))
        return Invoice.objects.create(user=self.user, date=datetime.date(2026, 10, 1), **kw)

    def test_sales_follow_place_of_supply_then_customer_state(self):
        self.assertEqual(supply_type(self.invoice(receiver=self.mh), 29), 'inter')
        self.assertEqual(supply_type(self.invoice(receiver=self.ka), 29), 'intra')
        # an explicit place of supply wins over the customer's state
        self.assertEqual(supply_type(self.invoice(receiver=self.mh, place_of_supply=29), 29), 'intra')
        self.assertIsNone(supply_type(self.invoice(), 29))

    def test_purchases_compare_vendor_state_with_ours(self):
        vendor = Vendor.objects.create(user=self.user, name='V', state_code=27)
        inv = self.invoice(vendor=vendor, invoice_type='purchase')
        self.assertEqual(supply_type(inv, 29), 'inter')

    def test_pdf_serializer_and_yaml_footer_print_igst(self):
        data = InvoiceSerializerForPDF(self.invoice(receiver=self.mh)).data
        self.assertEqual(data['supply_type'], 'inter')

        template = YamalReader(yaml_raw_data={'Bill': {
            'harder': [],
            'footer': [
                {'center_gst_amount': {'x': 1, 'y': 30, 'label': 'center_gst_amount', 'prefix': 'CGST Amount : '}},
                {'state_gst_amount': {'x': 1, 'y': 20, 'label': 'state_gst_amount', 'prefix': 'SGST Amount : '}},
            ],
            'product': {'product_list': []},
        }})
        data['products'] = []
        data['total_final_amount'] = '1180'
        fill = FillValue(data, template)
        fill.raw_footer_data.update(tax_heads(1000, 180, 'inter'))
        fill.set_footer()
        by_label = {f.label: f for f in fill.footers}
        self.assertEqual(by_label['center_gst_amount'].value, 180)
        self.assertEqual(by_label['center_gst_amount'].prefix, 'IGST Amount : ')
        self.assertEqual(by_label['state_gst_amount'].value, '')


# ── 2. server-side line maths ──────────────────────────────────────────────

class Col:
    def __init__(self, title, calc=True, formula='', outside=False):
        self.input_title, self.is_calculable = title, calc
        self.formula, self.on_with_out_gst_amount = formula, outside


class LineCalcTests(SimpleTestCase):

    def test_qty_rate_gst(self):
        props = [(Col('Quantity'), '2'), (Col('Rate'), '100'), (Col('GST'), '18')]
        self.assertEqual(calculate_line(props), (Decimal('236.00'), Decimal('36.00')))

    def test_renamed_gst_column_is_tax_not_a_multiplier(self):
        for title in ('GST %', 'gst%', 'Tax', 'GST Rate', 'IGST'):
            props = [(Col('Quantity'), '2'), (Col('Rate'), '100'), (Col(title), '18')]
            self.assertEqual(calculate_line(props), (Decimal('236.00'), Decimal('36.00')), title)
        self.assertFalse(is_gst_column('GST Amount'))

    def test_formulas_inside_and_outside_the_gst_base(self):
        props = [(Col('Quantity'), '1'), (Col('Rate'), '100'),
                 (Col('Discount', formula='%-'), '10'),            # 90 taxable
                 (Col('Freight', formula='+', outside=True), '50'),
                 (Col('GST'), '18')]                               # 16.20
        self.assertEqual(calculate_line(props), (Decimal('156.20'), Decimal('16.20')))

    def test_no_amount_inputs_means_nothing_to_recompute(self):
        self.assertIsNone(calculate_line([(Col('Name', calc=False), 'Widget'), (Col('GST'), '18')]))

    def test_rate_validation(self):
        for bad in ('abc', '-5', '180'):
            self.assertIsNotNone(gst_rate_error(bad), bad)
        for good in ('', None, '18', '18%', '0.25', '40'):
            self.assertIsNone(gst_rate_error(good), good)


class ServerTotalsApiTests(TestCase):
    """Replays the mobile app's line-item calls with wrong client amounts."""

    def setUp(self):
        cache.clear()
        company = UserCompanies.objects.create(company_name='Acme', is_varified=True, state_code=29)
        self.user = User.objects.create_user(username='api', email='a@e.com', password='pw-123456')
        self.user.user_company = company
        self.user.is_company_admin = True
        self.user.save()
        give_plan(company, ['invoicing', 'advanced_reports'])
        admin_role, _ = ensure_company_roles(CompanyRole, CompanyPermission, company)
        admin_role.users.add(self.user)
        self.cols = {
            title: new_product_in_frontend.objects.create(
                user=self.user, input_title=title, size=1, is_show=True, is_calculable=calc)
            for title, calc in [('Name', False), ('Quantity', True), ('Rate', True), ('GST %', True)]
        }
        self.c = APIClient()
        token = self.c.post('/api/login/', {'username': 'api', 'password': 'pw-123456'},
                            format='json', HTTP_X_CLIENT='mobile').data['access']
        self.c.cookies.clear()
        self.c.credentials(HTTP_AUTHORIZATION=f'Bearer {token}', HTTP_X_CLIENT='mobile')

    def post(self, url, body, expect=200):
        res = self.c.post(url, body, format='json')
        self.assertEqual(res.status_code, expect, res.content)
        return res.data

    def add_line(self, inv_id, values, sent_total, sent_gst):
        amounts = {'gst_amount': sent_gst, 'total_amount': sent_total}
        product = self.post('/api/product/', {'product_properties': '', **amounts})
        self.post(f'/api/invoice/{inv_id}/product/add/', {'product_id': product['id']})
        ids = [self.post('/api/product/properties/', {
            'new_product_in_frontend': col.id, 'value': values[t]})['id'] for t, col in self.cols.items()]
        return self.post(f'/api/product/{product["id"]}/update/',
                         {'product_properties': ','.join(map(str, ids)), **amounts})

    def test_stored_totals_follow_the_lines_not_the_client(self):
        inv = self.post('/api/invoice/', {'date': '2026-10-11', 'invoice_type': 'sales',
                                          'total_final_amount': '999.00', 'gst_final_amount': '0.00'})
        # an old client that only knew the title "GST" would send 3600 / 0 here
        line = self.add_line(inv['id'], {'Name': 'W', 'Quantity': '2', 'Rate': '100', 'GST %': '18'},
                             '3600.00', '0.00')
        self.assertEqual((line['total_amount'], line['gst_amount']), ('236.00', '36.00'))
        stored = Invoice.objects.get(id=inv['id'])
        self.assertEqual((stored.total_final_amount, stored.gst_final_amount),
                         (Decimal('236.00'), Decimal('36.00')))

        # and a later client totals patch can't override the lines
        self.post(f'/api/invoice/{inv["id"]}/update/', {'total_final_amount': '1.00', 'gst_final_amount': '0.00'})
        stored.refresh_from_db()
        self.assertEqual(stored.gst_final_amount, Decimal('36.00'))

    def test_header_only_invoice_keeps_its_totals(self):
        inv = self.post('/api/invoice/', {'date': '2026-10-11', 'invoice_type': 'purchase',
                                          'total_final_amount': '1180.00', 'gst_final_amount': '180.00'})
        stored = Invoice.objects.get(id=inv['id'])
        self.assertEqual(stored.gst_final_amount, Decimal('180.00'))

    def test_bad_gst_rate_is_rejected(self):
        res = self.c.post('/api/product/properties/', {
            'new_product_in_frontend': self.cols['GST %'].id, 'value': 'eighteen'}, format='json')
        self.assertEqual(res.status_code, 400, res.content)
        self.assertIn('value', res.data)

    def test_gst_summary_flags_off_slab_rates(self):
        inv = self.post('/api/invoice/', {'date': datetime.date.today().isoformat(), 'invoice_type': 'sales',
                                          'total_final_amount': '0', 'gst_final_amount': '0'})
        self.add_line(inv['id'], {'Name': 'W', 'Quantity': '1', 'Rate': '100', 'GST %': '17'}, '117', '17')
        codes = [i['code'] for i in self.c.get('/api/gst-summary/', {'period': 'this_month'}).data['data_quality']]
        self.assertIn('non_standard_rate', codes)

    # ── 4. notes move the liability ──

    def test_credit_note_with_gst_reduces_net_payable(self):
        today = datetime.date.today()
        cust = Customers.objects.create(user=self.user, name='B', state_code=29)
        Invoice.objects.create(user=self.user, receiver=cust, date=today, invoice_type='sales',
                               total_final_amount=Decimal('1180'), gst_final_amount=Decimal('180'))
        CreditDebitNote.objects.create(user=self.user, customer=cust, note_type='credit',
                                       amount=Decimal('118'), gst_amount=Decimal('18'), date=today)
        d = self.c.get('/api/gst-summary/', {'period': 'this_month'}).data
        self.assertEqual(d['output_gst'], 180)
        self.assertEqual(d['output_tax_adjustment'], -18)
        self.assertEqual(d['net_gst_payable'], 162)
        self.assertTrue(d['notes_reduce_liability'])

        CreditDebitNote.objects.create(user=self.user, customer=cust, note_type='credit',
                                       amount=Decimal('50'), date=today)
        d = self.c.get('/api/gst-summary/', {'period': 'this_month'}).data
        self.assertEqual(d['net_gst_payable'], 162)          # the untaxed note is not guessed
        self.assertFalse(d['notes_reduce_liability'])
        self.assertIn('notes_without_gst', [i['code'] for i in d['data_quality']])


class NoteTotalsTests(TestCase):

    def test_vendor_notes_adjust_input_credit(self):
        user = User.objects.create_user(username='n', password='x12345678')
        vendor = Vendor.objects.create(user=user, name='V')
        cust = Customers.objects.create(user=user, name='C')
        d = datetime.date(2026, 10, 5)
        CreditDebitNote.objects.create(user=user, vendor=vendor, note_type='credit',
                                       amount=Decimal('59'), gst_amount=Decimal('9'), date=d)
        CreditDebitNote.objects.create(user=user, customer=cust, note_type='debit',
                                       amount=Decimal('118'), gst_amount=Decimal('18'), date=d)
        t = note_totals(CreditDebitNote.objects.all(), datetime.date(2026, 10, 1), datetime.date(2026, 10, 31))
        self.assertEqual(t['input_tax_adjustment'], Decimal('-9'))
        self.assertEqual(t['output_tax_adjustment'], Decimal('18'))
        self.assertEqual(t['notes_without_gst'], 0)


# ── 3. exports ─────────────────────────────────────────────────────────────

class ExportPlaceOfSupplyTests(SimpleTestCase):

    def test_96_other_countries_is_a_valid_place_of_supply(self):
        self.assertTrue(is_valid_state_code(96))

    def test_96_is_still_not_a_gstin_state(self):
        from accounts.gst_utils import parse_gstin
        with self.assertRaises(ValueError):
            parse_gstin('96ABCDE1234F1Z5')
