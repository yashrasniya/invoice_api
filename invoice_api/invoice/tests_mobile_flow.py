"""Replays the exact call sequence of MobileApp/services/invoices.ts (JSON bodies,
bearer auth) so a drift between the app and the API shows up here, not on a phone."""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.authz_seed import ensure_company_roles
from accounts.models import CompanyPermission, CompanyRole, UserCompanies
from invoice.models import Invoice, new_product_in_frontend
from invoice.tests_numbering import give_plan

User = get_user_model()


class MobileInvoiceFlowTest(TestCase):
    def setUp(self):
        cache.clear()   # plan/feature lookups are cached per company id, and ids repeat across tests
        company = UserCompanies.objects.create(company_name='Acme', is_varified=True)
        self.user = User.objects.create_user(username='mob', email='m@e.com', password='pw-123456')
        self.user.user_company = company
        self.user.is_company_admin = True
        self.user.save()
        give_plan(company, ['invoicing'])
        admin_role, _ = ensure_company_roles(CompanyRole, CompanyPermission, company)
        admin_role.users.add(self.user)

        # a typical column config: Name, Quantity, Rate (multipliers) and GST
        self.cols = {
            title: new_product_in_frontend.objects.create(
                user=self.user, input_title=title, size=1, is_show=True,
                is_calculable=calc)
            for title, calc in [('Name of Product', False), ('Quantity', True),
                                ('Rate', True), ('GST', True)]
        }

        self.client = APIClient()
        token = self.client.post('/api/login/', {'username': 'mob', 'password': 'pw-123456'},
                                 format='json', HTTP_X_CLIENT='mobile').data['access']
        self.client.cookies.clear()
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}', HTTP_X_CLIENT='mobile')

    def post(self, url, body, expect=200):
        res = self.client.post(url, body, format='json')
        self.assertEqual(res.status_code, expect, res.content)
        return res.data

    def add_line(self, invoice_id, values, total, gst):
        amounts = {'gst_amount': gst, 'total_amount': total}
        product = self.post('/api/product/', {'product_properties': '', **amounts})
        self.post(f'/api/invoice/{invoice_id}/product/add/', {'product_id': product['id']})
        ids = []
        for title, col in self.cols.items():
            p = self.post('/api/product/properties/', {
                'new_product_in_frontend': col.id, 'value': values[title]})
            ids.append(p['id'])
        self.post(f'/api/product/{product["id"]}/update/',
                  {'product_properties': ','.join(map(str, ids)), **amounts})
        return product['id']

    def test_full_lifecycle(self):
        customer = self.post('/api/companies/', {
            'name': 'Buyer Ltd', 'address': 'Pune', 'gst_number': '27AAAAA0000A1Z5',
            'state': 'MH', 'state_code': 27, 'phone_number': None})

        inv = self.post('/api/invoice/', {
            'receiver': customer['id'], 'date': '2026-10-11', 'payment_status': 'unpaid',
            'invoice_type': 'sales', 'total_final_amount': '236.00', 'gst_final_amount': '36.00'})
        self.assertTrue(inv['invoice_number'] is not None or inv['id'])  # server may auto-number

        pid = self.add_line(inv['id'], {'Name of Product': 'Widget', 'Quantity': '2',
                                        'Rate': '100', 'GST': '18'}, '236.00', '36.00')

        got = self.client.get('/api/invoice/', {'id': inv['id']}).data['results'][0]
        self.assertEqual(len(got['products']), 1)
        self.assertEqual(len(got['products'][0]['product_properties']), 4)
        names = {p['new_product_in_frontend']['input_title']: p['value']
                 for p in got['products'][0]['product_properties']}
        self.assertEqual(names['Name of Product'], 'Widget')
        self.assertEqual(Decimal(got['total_final_amount']), Decimal('236.00'))

        upd = self.post(f'/api/invoice/{inv["id"]}/update/',
                        {'payment_status': 'paid', 'payment_method': 'upi'})
        self.assertEqual(upd['payment_status'], 'paid')

        # editing: clearing the number must store NULL, not ''
        upd = self.post(f'/api/invoice/{inv["id"]}/update/', {'invoice_number': ''})
        self.assertIsNone(upd['invoice_number'])

        # removing a line item
        res = self.client.delete(f'/api/product/{pid}/update/')
        self.assertEqual(res.status_code, 204)
        got = self.client.get('/api/invoice/', {'id': inv['id']}).data['results'][0]
        self.assertEqual(got['products'], [])

        res = self.client.delete(f'/api/invoice/?id={inv["id"]}')
        self.assertEqual(res.status_code, 204)
        self.assertFalse(Invoice.objects.filter(id=inv['id']).exists())

    def test_edit_existing_line_item(self):
        # replays MobileApp updateLineItem(): update changed values in place, attach any missing column, new amounts
        customer = self.post('/api/companies/', {'name': 'B', 'address': '', 'gst_number': '',
                                                 'state': '', 'state_code': None, 'phone_number': None})
        inv = self.post('/api/invoice/', {'receiver': customer['id'], 'date': '2026-10-01', 'invoice_type': 'sales',
                                          'payment_status': 'unpaid', 'total_final_amount': '236.00', 'gst_final_amount': '36.00'})
        pid = self.add_line(inv['id'], {'Name of Product': 'Widget', 'Quantity': '2', 'Rate': '100', 'GST': '18'}, '236.00', '36.00')

        line = self.client.get('/api/invoice/', {'id': inv['id']}).data['results'][0]['products'][0]
        by_title = {p['new_product_in_frontend']['input_title']: p for p in line['product_properties']}

        # change quantity 2 -> 5 and rename: 5 x 100 = 500, +18% = 590
        self.post(f'/api/product/properties/{by_title["Quantity"]["id"]}/update/', {'value': '5'})
        self.post(f'/api/product/properties/{by_title["Name of Product"]["id"]}/update/', {'value': 'Widget Pro'})
        self.post(f'/api/product/{pid}/update/', {'gst_amount': '90.00', 'total_amount': '590.00'})
        # then the app recomputes the invoice totals from its lines
        self.post(f'/api/invoice/{inv["id"]}/update/', {'total_final_amount': '590.00', 'gst_final_amount': '90.00'})

        got = self.client.get('/api/invoice/', {'id': inv['id']}).data['results'][0]
        vals = {p['new_product_in_frontend']['input_title']: p['value'] for p in got['products'][0]['product_properties']}
        self.assertEqual(vals['Quantity'], '5')
        self.assertEqual(vals['Name of Product'], 'Widget Pro')
        self.assertEqual(vals['Rate'], '100')                       # untouched columns keep their value
        self.assertEqual(len(got['products']), 1)                   # edited in place, not duplicated
        self.assertEqual(Decimal(got['products'][0]['total_amount']), Decimal('590.00'))
        self.assertEqual(Decimal(got['total_final_amount']), Decimal('590.00'))

        # a column the line never had (added to the company's config later) is created and attached on edit
        extra = new_product_in_frontend.objects.create(user=self.user, input_title='Notes', size=1, is_show=True, is_calculable=False)
        newprop = self.post('/api/product/properties/', {'new_product_in_frontend': extra.id, 'value': 'fragile'})
        self.post(f'/api/product/{pid}/update/', {'product_properties': str(newprop['id']), 'gst_amount': '90.00', 'total_amount': '590.00'})
        got = self.client.get('/api/invoice/', {'id': inv['id']}).data['results'][0]
        titles = {p['new_product_in_frontend']['input_title'] for p in got['products'][0]['product_properties']}
        self.assertIn('Notes', titles)
        self.assertEqual(len(got['products'][0]['product_properties']), 5)

    def test_customer_edit_and_vendor_roundtrip(self):
        c = self.post('/api/companies/', {'name': 'A', 'address': '', 'gst_number': '',
                                          'state': '', 'state_code': None, 'phone_number': None})
        c2 = self.post(f'/api/companies/{c["id"]}/', {'name': 'A2', 'address': 'X', 'gst_number': '',
                                                      'state': '', 'state_code': 29, 'phone_number': '9876543210'})
        self.assertEqual(c2['name'], 'A2')
        v = self.post('/api/vendors/', {'name': 'V', 'address': '', 'gst_number': '',
                                        'state': '', 'state_code': None, 'phone_number': None})
        listed = self.client.get('/api/vendors/', {'page': 1, 'page_size': 20}).data
        self.assertEqual([r['id'] for r in listed['results']], [v['id']])
