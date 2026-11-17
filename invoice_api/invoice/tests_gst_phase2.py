"""GST roadmap Phase 2: GST treatment, SEZ / deemed exports, LUT,
nil / exempt / non-GST lines and reverse charge."""
import datetime
import json
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.authz_seed import ensure_company_roles
from accounts.models import CompanyPermission, CompanyRole, UserCompanies
from companies.models import Customers, Vendor
from invoice.line_calc import recompute_for_product
from invoice.models import Invoice, Product, Product_properties, new_product_in_frontend
from invoice.serializers import InvoiceSerializerForPDF
from invoice.tests_numbering import give_plan
from invoice_api.gst import gst_period_bounds, supply_type

User = get_user_model()
SELLER = '29AAGCB7383J1Z4'     # Karnataka
MH_GSTIN = '27AAPFU0939F1ZV'   # Maharashtra
KA_GSTIN = '29ABCDE1234F1ZW'   # Karnataka


class Base(TestCase):

    def setUp(self):
        cache.clear()
        self.company = UserCompanies.objects.create(
            company_name='Seller', is_varified=True, state_code=29, company_gst_number=SELLER)
        self.user = User.objects.create_user(username='p2', email='p2@e.com', password='pw-123456')
        self.user.user_company = self.company
        self.user.is_company_admin = True
        self.user.save()
        give_plan(self.company, ['invoicing', 'advanced_reports', 'purchases_invoice'])
        role, _ = ensure_company_roles(CompanyRole, CompanyPermission, self.company)
        role.users.add(self.user)
        self.c = APIClient()
        self.c.force_authenticate(self.user)
        self.cols = {t: new_product_in_frontend.objects.create(
            user=self.user, input_title=t, size=1, is_calculable=calc)
            for t, calc in [('Name', False), ('HSN', False), ('Quantity', True), ('Rate', True), ('GST', True)]}
        self.start, self.end, _ = gst_period_bounds('last_month')
        self.day = self.start + datetime.timedelta(days=3)

    def party(self, **kw):
        kw.setdefault('name', 'P')
        kw.setdefault('phone_number', None)
        return self.c.post('/api/companies/', kw, format='json')

    def invoice(self, number, customer, lines, inv_type='sales', **kw):
        inv = Invoice.objects.create(user=self.user, invoice_number=number, receiver=customer,
                                     date=kw.pop('date', self.day), invoice_type=inv_type,
                                     total_final_amount=0, gst_final_amount=0, **kw)
        for values in lines:
            category = values.pop('category', 'taxable')
            p = Product.objects.create(user=self.user, gst_amount=0, total_amount=0, tax_category=category)
            for title, value in values.items():
                p.product_properties.add(Product_properties.objects.create(
                    new_product_in_frontend=self.cols[title], value=value))
            inv.products.add(p)
            recompute_for_product(p)
        inv.refresh_from_db()
        return inv

    def line(self, rate='1000', gst='18', hsn='8471', **kw):
        return {'Name': 'Item', 'HSN': hsn, 'Quantity': '1', 'Rate': rate, 'GST': gst, **kw}

    def gstr1(self):
        return self.c.get('/api/gstr1/', {'period': 'last_month'}).data

    def portal(self):
        res = self.c.get('/api/gstr1/', {'period': 'last_month', 'download': 1})
        self.assertEqual(res.status_code, 200, getattr(res, 'data', res.content))
        return json.loads(res.content)


class TreatmentTests(Base):

    def test_treatment_follows_the_gstin_when_not_sent(self):
        r = self.party(gst_number=MH_GSTIN)
        self.assertEqual(r.data['gst_treatment'], 'registered')
        r2 = self.c.post(f"/api/companies/{r.data['id']}/", {'name': 'P', 'gst_number': '', 'phone_number': None,
                                                              'state_code': 27}, format='json')
        self.assertEqual(r2.data['gst_treatment'], 'unregistered')

    def test_treatment_must_agree_with_the_gstin(self):
        self.assertEqual(self.party(gst_treatment='sez').status_code, 400)                    # needs a GSTIN
        self.assertEqual(self.party(gst_number=MH_GSTIN, gst_treatment='consumer').status_code, 400)
        r = self.party(gst_number=MH_GSTIN, gst_treatment='composition')
        self.assertEqual((r.status_code, r.data['gst_treatment']), (200, 'composition'))

    def test_overseas_is_placed_in_other_countries(self):
        r = self.party(gst_treatment='overseas', state='')
        self.assertEqual((r.data['state_code'], r.data['gst_treatment']), (96, 'overseas'))

    def test_sez_is_always_igst(self):
        sez = Customers.objects.create(user=self.user, name='SEZ unit', gst_number=KA_GSTIN, state_code=29,
                                       gst_treatment='sez')
        inv = Invoice.objects.create(user=self.user, receiver=sez, invoice_type='sales')
        self.assertEqual(supply_type(inv, 29), 'inter')          # same state, still IGST


class Gstr1TreatmentTests(Base):

    def test_sez_with_and_without_payment(self):
        sez = Customers.objects.create(user=self.user, name='SEZ', gst_number=KA_GSTIN, state_code=29,
                                       gst_treatment='sez')
        self.invoice('INV-1', sez, [self.line()])                  # IGST charged → SEWP
        self.invoice('INV-2', sez, [self.line(gst='0')])           # no IGST, no LUT → error
        codes = [i['code'] for i in self.gstr1()['issues'] if i['level'] == 'error']
        self.assertEqual(codes, ['lut_missing'])

        self.company.lut_number, self.company.lut_valid_from, self.company.lut_valid_to = (
            'AD290326000001X', self.start, self.end)
        self.company.save()
        cache.clear()
        rows = {r['inum']: r for r in self.portal()['b2b'][0]['inv']}
        self.assertEqual((rows['INV-1']['inv_typ'], rows['INV-1']['itms'][0]['itm_det']['iamt']), ('SEWP', 180.0))
        self.assertEqual(rows['INV-2']['inv_typ'], 'SEWOP')

    def test_expired_lut_blocks_an_export_without_igst(self):
        self.company.lut_number = 'AD290326000001X'
        self.company.lut_valid_from = datetime.date(2020, 4, 1)
        self.company.lut_valid_to = datetime.date(2021, 3, 31)
        self.company.save()
        cache.clear()
        buyer = Customers.objects.create(user=self.user, name='US', gst_treatment='overseas', state_code=96)
        self.invoice('INV-1', buyer, [self.line(gst='0')])
        self.assertIn('lut_missing', [i['code'] for i in self.gstr1()['issues']])

    def test_overseas_customer_without_place_of_supply_is_an_export(self):
        buyer = Customers.objects.create(user=self.user, name='US', gst_treatment='overseas')
        self.invoice('INV-1', buyer, [self.line()])               # IGST paid → WPAY, no LUT needed
        f = self.portal()
        self.assertEqual(f['exp'][0]['exp_typ'], 'WPAY')

    def test_deemed_export_and_composition(self):
        de = Customers.objects.create(user=self.user, name='EOU', gst_number=MH_GSTIN, state_code=27,
                                      gst_treatment='deemed_export')
        comp = Customers.objects.create(user=self.user, name='Comp', gst_number=KA_GSTIN, state_code=29,
                                        gst_treatment='composition')
        self.invoice('INV-1', de, [self.line()])
        self.invoice('INV-2', comp, [self.line()])
        by_ctin = {r['ctin']: r['inv'][0] for r in self.portal()['b2b']}
        self.assertEqual(by_ctin[MH_GSTIN]['inv_typ'], 'DE')
        self.assertEqual((by_ctin[KA_GSTIN]['inv_typ'], by_ctin[KA_GSTIN]['itms'][0]['itm_det']['camt']), ('R', 90.0))

    def test_table_8_columns(self):
        walkin = Customers.objects.create(user=self.user, name='Walk-in', state_code=29, gst_treatment='consumer')
        self.invoice('INV-1', walkin, [self.line(gst='0', rate='100'),
                                       self.line(gst='0', rate='200', category='exempt'),
                                       self.line(gst='0', rate='300', hsn='', category='non_gst'),
                                       self.line(rate='1000')])
        f = self.portal()
        self.assertEqual(f['nil']['inv'], [{'sply_ty': 'INTRAB2C', 'nil_amt': 100.0, 'expt_amt': 200.0,
                                            'ngsup_amt': 300.0}])
        self.assertNotIn('', {r['hsn_sc'] for r in f['hsn']['hsn_b2c']})     # non-GST line not in Table 12

    def test_a_category_on_a_taxed_line_is_an_error(self):
        walkin = Customers.objects.create(user=self.user, name='Walk-in', state_code=29)
        self.invoice('INV-1', walkin, [self.line(category='exempt')])
        self.assertIn('category_rate', [i['code'] for i in self.gstr1()['issues']])


class ReverseChargeTests(Base):

    def test_rcm_invoice_total_excludes_the_tax(self):
        b2b = Customers.objects.create(user=self.user, name='Reg', gst_number=MH_GSTIN, state_code=27,
                                       gst_treatment='registered')
        inv = self.invoice('INV-1', b2b, [self.line()], reverse_charge=True)
        self.assertEqual((inv.total_final_amount, inv.gst_final_amount), (Decimal('1000.00'), Decimal('180.00')))

        pdf = InvoiceSerializerForPDF(inv).data
        self.assertEqual((pdf['reverse_charge'], pdf['rcm_tax_amount']), ('Yes', '180.00'))

        row = self.portal()['b2b'][0]['inv'][0]
        self.assertEqual((row['rchrg'], row['val'], row['itms'][0]['itm_det']['iamt']), ('Y', 1180.0, 180.0))

    def test_rcm_to_an_unregistered_buyer_is_an_error(self):
        walkin = Customers.objects.create(user=self.user, name='Walk-in', state_code=29)
        self.invoice('INV-1', walkin, [self.line()], reverse_charge=True)
        self.assertIn('rcm_unregistered', [i['code'] for i in self.gstr1()['issues']])

    def test_gst_summary_nets_reverse_charge(self):
        today = datetime.date.today()
        b2b = Customers.objects.create(user=self.user, name='Reg', gst_number=MH_GSTIN, state_code=27)
        vendor = Vendor.objects.create(user=self.user, name='GTA')
        self.invoice('S-1', b2b, [self.line()], date=today)                          # 180 output
        self.invoice('S-2', b2b, [self.line()], date=today, reverse_charge=True)     # buyer's tax
        p = self.invoice('P-1', None, [self.line(rate='500', gst='5')], inv_type='purchase', date=today,
                         reverse_charge=True)
        p.vendor = vendor
        p.save()
        d = self.c.get('/api/gst-summary/', {'period': 'this_month'}).data
        self.assertEqual(d['output_gst'], 180)
        self.assertEqual(d['rcm_sales_tax'], 180)
        self.assertEqual(d['rcm_payable'], 25)
        self.assertEqual(d['input_gst'], 25)               # RCM tax paid is claimable
        self.assertEqual(d['net_gst_payable'], 180)        # 180 + 25 payable − 25 credit
        self.assertEqual(d['total_sales_taxable'], 2000)


class LutValidationTests(Base):

    def check(self, **data):
        from accounts.serializers.UserCompanies import UserCompaniesSerializer
        ser = UserCompaniesSerializer(self.company, data=data, partial=True)
        return ser.is_valid(), ser.errors

    def test_lut_needs_number_and_both_dates(self):
        ok, errors = self.check(lut_number='AD290326000001X')
        self.assertFalse(ok)
        self.assertIn('lut_number', errors)
        ok, errors = self.check(lut_number='AD290326000001X', lut_valid_from='2026-04-01', lut_valid_to='2026-03-31')
        self.assertIn('lut_valid_to', errors)
        ok, _ = self.check(lut_number='AD290326000001X', lut_valid_from='2026-04-01', lut_valid_to='2027-03-31')
        self.assertTrue(ok)
