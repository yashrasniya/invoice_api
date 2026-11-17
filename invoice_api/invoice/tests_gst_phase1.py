"""GST roadmap Phase 1: bad GST data is stopped when it's entered.

#1/#11 customer and vendor GSTINs (check character, state from the GSTIN),
#12 invoice-number rules on sales invoices, #6/#7 HSN/SAC + unit on items
and HSN cells, and GSTR-1's single "add an HSN column" message.
"""
import datetime

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.authz_seed import ensure_company_roles
from accounts.models import CompanyPermission, CompanyRole, UserCompanies
from companies.models import Customers
from invoice.line_calc import recompute_for_product
from invoice.models import Invoice, Product, Product_properties, new_product_in_frontend
from invoice.tests_numbering import give_plan
from invoice_api.gst import gst_period_bounds

User = get_user_model()
GOOD_MH = '27AAPFU0939F1ZV'


class Phase1Tests(TestCase):

    def setUp(self):
        cache.clear()
        self.company = UserCompanies.objects.create(
            company_name='Seller', is_varified=True, state_code=29, company_gst_number='29AAGCB7383J1Z4')
        self.user = User.objects.create_user(username='p1', email='p@e.com', password='pw-123456')
        self.user.user_company = self.company
        self.user.is_company_admin = True
        self.user.save()
        give_plan(self.company, ['invoicing', 'advanced_reports', 'inventory', 'purchases_invoice'])
        role, _ = ensure_company_roles(CompanyRole, CompanyPermission, self.company)
        role.users.add(self.user)
        self.c = APIClient()
        self.c.force_authenticate(self.user)

    def post(self, url, body):
        return self.c.post(url, body, format='json')

    # ── #1 / #11 ──

    def test_customer_gstin_with_a_typo_is_rejected(self):
        r = self.post('/api/companies/', {'name': 'B', 'gst_number': '27AAPFU0939F1ZW', 'state_code': None,
                                          'phone_number': None})
        self.assertEqual(r.status_code, 400)
        self.assertIn('gst_number', r.data)

    def test_customer_state_comes_from_the_gstin(self):
        r = self.post('/api/companies/', {'name': 'B', 'gst_number': ' 27aapfu0939f1zv ', 'state': '',
                                          'state_code': None, 'phone_number': None})
        self.assertEqual(r.status_code, 200, r.data)
        c = Customers.objects.get(id=r.data['id'])
        self.assertEqual((c.gst_number, c.state_code, c.state), (GOOD_MH, 27, 'Maharashtra'))

    def test_customer_gstin_and_a_different_state_conflict(self):
        r = self.post('/api/companies/', {'name': 'B', 'gst_number': GOOD_MH, 'state_code': 29,
                                          'phone_number': None})
        self.assertEqual(r.status_code, 400)
        self.assertIn('state_code', r.data)

    def test_unregistered_customer_keeps_the_chosen_state(self):
        r = self.post('/api/companies/', {'name': 'B', 'gst_number': '', 'state': 'Goa', 'state_code': 30,
                                          'phone_number': None})
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(Customers.objects.get(id=r.data['id']).state_code, 30)

    def test_vendor_gstin_is_checked_too(self):
        r = self.post('/api/vendors/', {'name': 'V', 'gst_number': '27AAPFU0938F1ZV', 'phone_number': None})
        self.assertEqual(r.status_code, 400)
        self.assertIn('gst_number', r.data)

    # ── #12 ──

    def invoice(self, number, inv_type='sales', date='2026-10-01'):
        return self.post('/api/invoice/', {'invoice_number': number, 'invoice_type': inv_type, 'date': date,
                                           'total_final_amount': '0', 'gst_final_amount': '0'})

    def test_sales_invoice_number_format(self):
        for bad in ('INV 001', 'INV#001', 'A' * 17):
            r = self.invoice(bad)
            self.assertEqual(r.status_code, 400, bad)
            self.assertIn('invoice_number', r.data)
        self.assertEqual(self.invoice('INV/26-27/001').status_code, 200)

    def test_sales_invoice_number_unique_within_the_fy(self):
        self.assertEqual(self.invoice('INV-1').status_code, 200)
        r = self.invoice('inv-1')
        self.assertEqual(r.status_code, 400)
        self.assertIn('already used', r.data['invoice_number'][0])
        # the same number in the next financial year is fine
        self.assertEqual(self.invoice('INV-1', date='2027-04-02').status_code, 200)

    def test_editing_an_invoice_without_changing_its_number_is_allowed(self):
        legacy = Invoice.objects.create(user=self.user, invoice_number='OLD NUMBER #1', invoice_type='sales',
                                        date=datetime.date(2026, 10, 1))
        r = self.post(f'/api/invoice/{legacy.id}/update/', {'invoice_number': 'OLD NUMBER #1',
                                                             'payment_status': 'paid'})
        self.assertEqual(r.status_code, 200, r.data)

    def test_purchase_bills_keep_the_vendors_number(self):
        self.assertEqual(self.invoice('VENDOR BILL #77 / 2026', inv_type='purchase').status_code, 200)

    # ── #6 / #7 ──

    def test_inventory_item_hsn_and_unit(self):
        base = {'sku': 'S1', 'name': 'Laptop', 'price': '1000', 'gst_percentage': '18'}
        r = self.post('/api/inventory/products/', {**base, 'hsn_code': '84 71', 'unit': 'pcs'})
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual((r.data['hsn_code'], r.data['unit']), ('8471', 'PCS'))
        r = self.post('/api/inventory/products/', {**base, 'sku': 'S2', 'hsn_code': '847'})
        self.assertEqual(r.status_code, 400)
        r = self.post('/api/inventory/products/', {**base, 'sku': 'S3', 'unit': 'furlongs'})
        self.assertEqual(r.status_code, 400)

    def test_hsn_cell_is_validated(self):
        col = new_product_in_frontend.objects.create(user=self.user, input_title='HSN Code', size=1)
        r = self.post('/api/product/properties/', {'new_product_in_frontend': col.id, 'value': '12AB'})
        self.assertEqual(r.status_code, 400)
        r = self.post('/api/product/properties/', {'new_product_in_frontend': col.id, 'value': '998314'})
        self.assertEqual(r.status_code, 200, r.data)

    def test_gstr1_says_add_an_hsn_column_once(self):
        cols = {t: new_product_in_frontend.objects.create(user=self.user, input_title=t, size=1, is_calculable=calc)
                for t, calc in [('Name', False), ('Quantity', True), ('Rate', True), ('GST', True)]}
        start, _, _ = gst_period_bounds('last_month')
        cust = Customers.objects.create(user=self.user, name='Walk-in', state_code=29)
        for n in range(3):
            inv = Invoice.objects.create(user=self.user, invoice_number=f'INV-{n}', receiver=cust,
                                         date=start + datetime.timedelta(days=2), invoice_type='sales')
            p = Product.objects.create(user=self.user, gst_amount=0, total_amount=0)
            for t, v in {'Name': 'X', 'Quantity': '1', 'Rate': '100', 'GST': '18'}.items():
                p.product_properties.add(Product_properties.objects.create(new_product_in_frontend=cols[t], value=v))
            inv.products.add(p)
            recompute_for_product(p)
        codes = [i['code'] for i in self.c.get('/api/gstr1/', {'period': 'last_month'}).data['issues']]
        self.assertEqual(codes.count('no_hsn_column'), 1)
        self.assertNotIn('hsn_missing', codes)
