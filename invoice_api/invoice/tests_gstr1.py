"""GSTR-1: each table, the portal JSON, and the checks that block filing."""
import datetime
import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from accounts.authz_seed import ensure_company_roles
from accounts.gst_utils import gstin_error
from accounts.models import CompanyPermission, CompanyRole, UserCompanies
from companies.models import Customers
from invoice.line_calc import recompute_for_product
from invoice.models import (CreditDebitNote, Invoice, Product, Product_properties,
                            new_product_in_frontend)
from invoice.tests_numbering import give_plan
from invoice_api.gst import gst_period_bounds
from invoice_api.gstr1 import snap_rate

User = get_user_model()

SELLER = '29AAGCB7383J1Z4'     # Karnataka
BUYER = '27AAPFU0939F1ZV'      # Maharashtra


class GstinChecksumTests(SimpleTestCase):

    def test_valid_gstins_pass(self):
        for g in (SELLER, BUYER, '27AAACR5055K1Z7'):
            self.assertIsNone(gstin_error(g), g)

    def test_a_single_typo_is_caught(self):
        self.assertIsNotNone(gstin_error('27AAPFU0939F1ZW'))   # wrong check char
        self.assertIsNotNone(gstin_error('27AAPFU0938F1ZV'))   # wrong digit
        self.assertIsNotNone(gstin_error('27AAPFU0939F1Z'))    # too short


class SnapRateTests(SimpleTestCase):

    def test_matches_a_slab_or_refuses(self):
        self.assertEqual(snap_rate(1000, 180), Decimal('18'))
        self.assertEqual(snap_rate(1000, 180.6), Decimal('18'))   # per-line rounding
        self.assertIsNone(snap_rate(1000, 170))
        self.assertEqual(snap_rate(500, 0), Decimal('0'))


class Gstr1Tests(TestCase):

    def setUp(self):
        cache.clear()
        self.company = UserCompanies.objects.create(
            company_name='Seller', is_varified=True, state_code=29, company_gst_number=SELLER)
        self.user = User.objects.create_user(username='g1', email='g@e.com', password='pw-123456')
        self.user.user_company = self.company
        self.user.is_company_admin = True
        self.user.save()
        give_plan(self.company, ['invoicing', 'advanced_reports'])
        role, _ = ensure_company_roles(CompanyRole, CompanyPermission, self.company)
        role.users.add(self.user)

        self.cols = {t: new_product_in_frontend.objects.create(
            user=self.user, input_title=t, size=1, is_show=True, is_calculable=calc)
            for t, calc in [('Name', False), ('HSN', False), ('Quantity', True),
                            ('Unit', False), ('Rate', True), ('GST', True)]}

        self.start, self.end, _ = gst_period_bounds('last_month')
        self.day = self.start + datetime.timedelta(days=4)

        self.b2b = Customers.objects.create(user=self.user, name='Reg MH', state_code=27, gst_number=BUYER)
        self.local = Customers.objects.create(user=self.user, name='Walk-in KA', state_code=29)
        self.far = Customers.objects.create(user=self.user, name='Unreg MH', state_code=27)
        self.abroad = Customers.objects.create(user=self.user, name='US buyer')

        self.c = APIClient()
        token = self.c.post('/api/login/', {'username': 'g1', 'password': 'pw-123456'},
                            format='json', HTTP_X_CLIENT='mobile').data['access']
        self.c.cookies.clear()
        self.c.credentials(HTTP_AUTHORIZATION=f'Bearer {token}', HTTP_X_CLIENT='mobile')

    def invoice(self, number, customer, lines, **kw):
        inv = Invoice.objects.create(user=self.user, invoice_number=number, receiver=customer,
                                     date=kw.pop('date', self.day), invoice_type='sales',
                                     total_final_amount=0, gst_final_amount=0, **kw)
        for values in lines:
            p = Product.objects.create(user=self.user, gst_amount=0, total_amount=0)
            for title, value in values.items():
                p.product_properties.add(Product_properties.objects.create(
                    new_product_in_frontend=self.cols[title], value=value))
            inv.products.add(p)
            recompute_for_product(p)
        inv.refresh_from_db()
        return inv

    def line(self, qty='1', rate='1000', gst='18', hsn='8471', name='Laptop', unit='Nos'):
        return {'Name': name, 'HSN': hsn, 'Quantity': qty, 'Unit': unit, 'Rate': rate, 'GST': gst}

    def get(self, **params):
        return self.c.get('/api/gstr1/', {'period': 'last_month', **params})

    def full_month(self):
        self.invoice('INV-001', self.b2b, [self.line(qty='2'), self.line(rate='500', gst='5', hsn='4901', name='Book')])
        self.invoice('INV-002', self.local, [self.line()])
        self.invoice('INV-003', self.far, [self.line(qty='100')])                 # 1.18 lakh inter-state
        self.invoice('INV-004', self.far, [self.line()])                          # small inter-state B2C
        self.invoice('INV-005', self.abroad, [self.line(gst='0')], place_of_supply=96)
        self.invoice('INV-006', self.local, [self.line(gst='0', hsn='0401', name='Milk', unit='Ltr')])

    def test_tables_and_portal_json(self):
        self.full_month()
        d = self.get().data
        self.assertTrue(d['ready_to_file'], d['issues'])
        counts = {t['table']: t['count'] for t in d['tables']}
        self.assertEqual(counts, {'b2b': 1, 'b2cl': 1, 'exp': 1, 'b2cs': 2, 'nil': 0, 'cdnr': 0, 'cdnur': 0})

        res = self.get(download=1)
        self.assertEqual(res.status_code, 200)
        f = json.loads(res.content)
        self.assertEqual(f['gstin'], SELLER)
        self.assertEqual(f['fp'], f'{self.end.month:02d}{self.end.year}')

        # 4A: inter-state to MH → IGST, one row per rate
        inv = f['b2b'][0]['inv'][0]
        self.assertEqual(f['b2b'][0]['ctin'], BUYER)
        self.assertEqual((inv['inum'], inv['pos'], inv['val']), ('INV-001', '27', 2885.0))
        self.assertEqual(inv['idt'], self.day.strftime('%d-%m-%Y'))
        rates = {i['itm_det']['rt']: i['itm_det'] for i in inv['itms']}
        self.assertEqual((rates[18]['txval'], rates[18]['iamt'], rates[18]['camt']), (2000.0, 360.0, 0.0))
        self.assertEqual(rates[5]['iamt'], 25.0)

        # 5: above ₹1 lakh inter-state B2C, invoice-wise
        self.assertEqual(f['b2cl'][0]['pos'], '27')
        self.assertEqual(f['b2cl'][0]['inv'][0]['inum'], 'INV-003')
        self.assertNotIn('camt', f['b2cl'][0]['inv'][0]['itms'][0]['itm_det'])

        # 7: aggregated by supply type / state / rate
        b2cs = {(r['sply_ty'], r['pos']): r for r in f['b2cs']}
        self.assertEqual((b2cs[('INTRA', '29')]['camt'], b2cs[('INTRA', '29')]['samt']), (90.0, 90.0))
        self.assertEqual(b2cs[('INTER', '27')]['iamt'], 180.0)

        # 6A: export without tax
        self.assertEqual(f['exp'][0]['exp_typ'], 'WOPAY')
        # 8: the 0% intra-state B2C line
        self.assertEqual(f['nil']['inv'], [{'sply_ty': 'INTRAB2C', 'nil_amt': 1000.0, 'expt_amt': 0, 'ngsup_amt': 0}])

        # 12: B2B and B2C tabs, unit mapped to UQC
        b2b_hsn = {r['hsn_sc']: r for r in f['hsn']['hsn_b2b']}
        self.assertEqual((b2b_hsn['8471']['qty'], b2b_hsn['8471']['uqc'], b2b_hsn['8471']['iamt']), (2.0, 'NOS', 360.0))
        b2c_codes = {(r['hsn_sc'], r['uqc']) for r in f['hsn']['hsn_b2c']}
        self.assertIn(('0401', 'LTR'), b2c_codes)

        # 13: one series INV-001..INV-006
        docs = f['doc_issue']['doc_det'][0]['docs']
        self.assertEqual((docs[0]['from'], docs[0]['to'], docs[0]['totnum']), ('INV-001', 'INV-006', 6))

    def test_cancelled_invoices_are_counted_in_table_13(self):
        self.invoice('INV-001', self.local, [self.line()])
        self.invoice('INV-002', self.local, [self.line()]).delete()
        docs = self.get().data['documents']
        self.assertEqual((docs[0]['totnum'], docs[0]['cancel'], docs[0]['net_issue']), (2, 1, 1))

    def test_credit_notes(self):
        inv = self.invoice('INV-001', self.b2b, [self.line()])
        CreditDebitNote.objects.create(user=self.user, customer=self.b2b, invoice=inv, note_type='credit',
                                       note_number='CN-1', amount=Decimal('118'), gst_amount=Decimal('18'),
                                       date=self.day)
        CreditDebitNote.objects.create(user=self.user, customer=self.local, note_type='credit',
                                       note_number='CN-2', amount=Decimal('118'), gst_amount=Decimal('18'),
                                       date=self.day)
        self.invoice('INV-002', self.local, [self.line()])
        f = json.loads(self.get(download=1).content)
        nt = f['cdnr'][0]['nt'][0]
        self.assertEqual((nt['ntty'], nt['nt_num'], nt['itms'][0]['itm_det']['iamt']), ('C', 'CN-1', 18.0))
        # the small B2C credit note nets into Table 7
        intra = next(r for r in f['b2cs'] if r['sply_ty'] == 'INTRA')
        self.assertEqual((intra['txval'], intra['camt']), (900.0, 81.0))

    def test_problems_block_the_download(self):
        bad = Customers.objects.create(user=self.user, name='Typo', state_code=27, gst_number='27AAPFU0939F1ZW')
        self.invoice('INV-001', bad, [self.line()])
        self.invoice('INV-002', self.local, [self.line(hsn='')])
        self.invoice('INV-003', self.local, [self.line(gst='17')])
        self.invoice('INV-004', self.local, [self.line()])
        self.invoice('INV-004', self.local, [self.line()])
        self.invoice('THIS-NUMBER-IS-TOO-LONG', self.local, [self.line()])
        Invoice.objects.create(user=self.user, invoice_number='INV-009', receiver=self.local, date=self.day,
                               invoice_type='sales', total_final_amount=Decimal('1170'), gst_final_amount=Decimal('170'))
        CreditDebitNote.objects.create(user=self.user, customer=self.local, note_type='credit',
                                       note_number='CN-1', amount=Decimal('100'), date=self.day)

        d = self.get().data
        self.assertFalse(d['ready_to_file'])
        codes = {i['code'] for i in d['issues'] if i['level'] == 'error'}
        self.assertTrue({'customer_gstin', 'hsn_missing', 'non_standard_rate', 'invoice_number_duplicate',
                         'invoice_number_format', 'rate_unknown', 'note_gst_missing'} <= codes, codes)
        ref = next(i['ref'] for i in d['issues'] if i['code'] == 'customer_gstin')
        self.assertEqual(ref['number'], 'INV-001')

        res = self.get(download=1)
        self.assertEqual(res.status_code, 409)
        self.assertTrue(res.data['issues'])

    def test_company_gstin_is_required(self):
        self.company.company_gst_number = ''
        self.company.save()
        cache.clear()
        d = self.get().data
        self.assertIn('company_gstin', {i['code'] for i in d['issues']})

    def test_invalid_period_rejected(self):
        self.assertEqual(self.get(period='this_fy').status_code, 400)
