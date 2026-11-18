"""GST roadmap Phase 3: GSTR-3B, ITC eligibility, quarterly filing / IFF and GSTR-9."""
import datetime
import json
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from accounts.authz_seed import ensure_company_roles
from accounts.models import CompanyPermission, CompanyRole, UserCompanies
from companies.models import Customers, Vendor
from invoice.line_calc import recompute_for_product
from invoice.models import CreditDebitNote, Invoice, Product, Product_properties, new_product_in_frontend
from invoice.tests_numbering import give_plan
from invoice_api.gstr3b import set_off

User = get_user_model()
SELLER = '29AAGCB7383J1Z4'     # Karnataka
MH_GSTIN = '27AAPFU0939F1ZV'   # Maharashtra
KA_GSTIN = '29ABCDE1234F1ZW'   # Karnataka
D = Decimal


def frozen(y, m, d):
    """Pin "today" for the period keys (last_month, this_quarter, ...)."""
    class FakeDate(datetime.date):
        @classmethod
        def today(cls):
            return cls(y, m, d)
    return mock.patch('invoice_api.gst.date', FakeDate)


class Base(TestCase):

    def setUp(self):
        cache.clear()
        self.company = UserCompanies.objects.create(
            company_name='Seller', is_varified=True, state_code=29, company_gst_number=SELLER,
            lut_number='AD290326000001X', lut_valid_from=datetime.date(2020, 4, 1),
            lut_valid_to=datetime.date(2099, 3, 31))
        self.user = User.objects.create_user(username='p3', email='p3@e.com', password='pw-123456')
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
        self.oct = datetime.date(2026, 10, 10)

    def invoice(self, number, lines, party=None, inv_type='sales', **kw):
        fields = {'vendor': party} if inv_type == 'purchase' else {'receiver': party}
        inv = Invoice.objects.create(user=self.user, invoice_number=number, date=kw.pop('date', self.oct),
                                     invoice_type=inv_type, total_final_amount=0, gst_final_amount=0,
                                     **fields, **kw)
        for values in lines:
            category = values.pop('category', 'taxable')
            itc = values.pop('itc', '')
            p = Product.objects.create(user=self.user, gst_amount=0, total_amount=0, tax_category=category,
                                       itc_eligibility=itc)
            for title, value in values.items():
                p.product_properties.add(Product_properties.objects.create(
                    new_product_in_frontend=self.cols[title], value=value))
            inv.products.add(p)
            recompute_for_product(p)
        inv.refresh_from_db()
        return inv

    def line(self, rate='1000', gst='18', hsn='8471', **kw):
        return {'Name': 'Item', 'HSN': hsn, 'Quantity': '1', 'Rate': rate, 'GST': gst, **kw}

    def get(self, url, **params):
        r = self.c.get(url, params)
        self.assertEqual(r.status_code, 200, getattr(r, 'data', r.content))
        return r.data


def rows(items):
    return {r['key']: r for r in items}


class Gstr3bTests(Base):

    def month(self):
        reg = Customers.objects.create(user=self.user, name='Reg MH', gst_number=MH_GSTIN, state_code=27)
        walkin = Customers.objects.create(user=self.user, name='Walk-in', state_code=29)
        far = Customers.objects.create(user=self.user, name='Unreg MH', state_code=27)
        abroad = Customers.objects.create(user=self.user, name='US', gst_treatment='overseas', state_code=96)
        self.invoice('S-1', [self.line()], reg)                                        # B2B inter
        self.invoice('S-2', [self.line()], walkin)                                     # B2C intra
        self.invoice('S-3', [self.line(rate='500')], far)                              # B2C inter small
        self.invoice('S-4', [self.line(rate='2000', gst='0')], abroad)                 # export under LUT
        self.invoice('S-5', [self.line(rate='300', gst='0'),
                             self.line(rate='200', gst='0', category='exempt'),
                             self.line(rate='100', gst='0', hsn='', category='non_gst')], walkin)
        self.invoice('S-6', [self.line()], reg, reverse_charge=True)                   # buyer pays

        v_ka = Vendor.objects.create(user=self.user, name='KA supplier', gst_number=KA_GSTIN, state_code=29)
        v_mh = Vendor.objects.create(user=self.user, name='MH supplier', gst_number=MH_GSTIN, state_code=27)
        v_unreg = Vendor.objects.create(user=self.user, name='Local GTA', state_code=29)
        v_abroad = Vendor.objects.create(user=self.user, name='US SaaS', gst_treatment='overseas', state_code=96)
        self.invoice('P-1', [self.line(rate='2000')], v_ka, inv_type='purchase')
        self.invoice('P-2', [self.line()], v_mh, inv_type='purchase', itc_eligibility='blocked')
        self.invoice('P-3', [self.line(rate='500', gst='5', hsn='9965')], v_unreg, inv_type='purchase',
                     reverse_charge=True)
        self.invoice('P-4', [self.line()], v_unreg, inv_type='purchase')               # no GSTIN: no ITC
        self.invoice('P-5', [self.line(hsn='998314')], v_abroad, inv_type='purchase')  # import of services

    def test_outward_tables(self):
        self.month()
        with frozen(2026, 11, 17):
            d = self.get('/api/gstr3b/', period='last_month')
        out = rows(d['outward'])
        self.assertEqual((out['3.1a']['taxable'], out['3.1a']['igst'], out['3.1a']['cgst'], out['3.1a']['sgst']),
                         (2500.0, 270.0, 90.0, 90.0))
        self.assertEqual((out['3.1b']['taxable'], out['3.1b']['igst']), (2000.0, 0.0))
        self.assertEqual(out['3.1c']['taxable'], 500.0)
        self.assertEqual(out['3.1e']['taxable'], 100.0)
        # reverse charge in: the RCM purchase and the imported service
        self.assertEqual((out['3.1d']['taxable'], out['3.1d']['igst'], out['3.1d']['cgst']), (1500.0, 180.0, 12.5))
        # the buyer's reverse-charge tax isn't ours
        self.assertEqual((d['buyer_pays_reverse_charge']['taxable'], d['buyer_pays_reverse_charge']['igst']),
                         (1000.0, 180.0))
        self.assertEqual(d['inter_state_unregistered'],
                         [{'buyer': 'unregistered', 'pos': '27', 'state': 'Maharashtra', 'taxable': 500.0,
                           'igst': 90.0}])

    def test_itc_and_payment(self):
        self.month()
        with frozen(2026, 11, 17):
            d = self.get('/api/gstr3b/', period='last_month')
        itc = rows(d['itc'])
        self.assertEqual((itc['4A5']['igst'], itc['4A5']['cgst'], itc['4A5']['sgst']), (180.0, 180.0, 180.0))
        self.assertEqual((itc['4A3']['cgst'], itc['4A3']['sgst']), (12.5, 12.5))
        self.assertEqual(itc['4A2']['igst'], 180.0)
        self.assertEqual(itc['4B1']['igst'], 180.0)                     # blocked
        self.assertEqual((itc['4C']['igst'], itc['4C']['cgst'], itc['4C']['sgst']), (180.0, 192.5, 192.5))
        self.assertIn('vendor_no_gstin', [i['code'] for i in d['issues']])

        pay = {r['head']: r for r in d['payment']['rows']}
        self.assertEqual((pay['IGST']['liability'], pay['IGST']['paid_igst_credit'],
                          pay['IGST']['paid_cgst_credit'], pay['IGST']['cash']), (270.0, 180.0, 90.0, 0.0))
        self.assertEqual((pay['CGST']['paid_cgst_credit'], pay['CGST']['cash']), (90.0, 0.0))
        # reverse-charge tax is always paid in cash
        self.assertEqual(d['payment']['cash_total'], 205.0)
        self.assertEqual(d['payment']['credit_carried_forward'], {'igst': 0.0, 'cgst': 12.5, 'sgst': 102.5})

    def test_line_override_of_itc(self):
        v = Vendor.objects.create(user=self.user, name='KA', gst_number=KA_GSTIN, state_code=29)
        self.invoice('P-1', [self.line(), self.line(rate='500', itc='blocked')], v, inv_type='purchase')
        with frozen(2026, 11, 17):
            itc = rows(self.get('/api/gstr3b/', period='last_month')['itc'])
        self.assertEqual((itc['4A5']['cgst'], itc['4B1']['cgst'], itc['4C']['cgst']), (135.0, 45.0, 90.0))

    def test_vendor_credit_note_reduces_itc(self):
        v = Vendor.objects.create(user=self.user, name='KA', gst_number=KA_GSTIN, state_code=29)
        self.invoice('P-1', [self.line()], v, inv_type='purchase')
        CreditDebitNote.objects.create(user=self.user, vendor=v, note_type='credit', note_number='VCN-1',
                                       amount=D('118'), gst_amount=D('18'), date=self.oct)
        with frozen(2026, 11, 17):
            itc = rows(self.get('/api/gstr3b/', period='last_month')['itc'])
        self.assertEqual((itc['4A5']['cgst'], itc['4A5']['sgst']), (81.0, 81.0))

    def test_sales_with_gstr1_errors_are_counted_as_left_out(self):
        walkin = Customers.objects.create(user=self.user, name='Walk-in', state_code=29)
        self.invoice('S-1', [self.line(gst='17')], walkin)
        with frozen(2026, 11, 17):
            d = self.get('/api/gstr3b/', period='last_month')
        self.assertEqual((d['sales_with_errors'], d['sales_left_out']), (1, 0))
        self.assertIn('gstr1_errors', [i['code'] for i in d['issues']])

    def test_company_gstin_problem_is_carried_over(self):
        self.company.company_gst_number = ''
        self.company.save()
        cache.clear()
        with frozen(2026, 11, 17):
            d = self.get('/api/gstr3b/', period='last_month')
        self.assertIn('company_gstin', [i['code'] for i in d['issues']])

    def test_itc_eligibility_is_saved_on_the_bill(self):
        r = self.c.post('/api/invoice/', {'invoice_number': 'B-9', 'invoice_type': 'purchase',
                                          'date': '2026-10-01', 'itc_eligibility': 'blocked',
                                          'total_final_amount': '0', 'gst_final_amount': '0'}, format='json')
        self.assertEqual((r.status_code, r.data['itc_eligibility']), (200, 'blocked'))


class LineFieldTests(Base):
    """The web sends line fields as form data to product/ and product/<id>/update/."""

    def test_category_and_itc_are_saved_on_a_line(self):
        r = self.c.post('/api/product/', {'product_properties': '', 'gst_amount': '0', 'total_amount': '0',
                                          'tax_category': 'exempt', 'itc_eligibility': 'blocked'})
        self.assertEqual(r.status_code, 200, r.data)
        p = Product.objects.get(id=r.data['id'])
        self.assertEqual((p.tax_category, p.itc_eligibility), ('exempt', 'blocked'))
        r = self.c.post(f'/api/product/{p.id}/update/', {'gst_amount': '0', 'total_amount': '0',
                                                         'tax_category': 'taxable', 'itc_eligibility': ''})
        self.assertEqual(r.status_code, 200, r.data)
        p.refresh_from_db()
        self.assertEqual((p.tax_category, p.itc_eligibility), ('taxable', ''))


class GstSettingsTests(Base):

    def test_admin_sets_frequency_and_lut(self):
        r = self.c.patch('/api/company/gst-settings/', {'gst_filing_frequency': 'quarterly',
                                                         'lut_number': 'AD290326000009Z',
                                                         'lut_valid_from': '2026-04-01',
                                                         'lut_valid_to': '2027-03-31'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.company.refresh_from_db()
        self.assertEqual((self.company.gst_filing_frequency, self.company.lut_number), ('quarterly', 'AD290326000009Z'))
        # clearing the LUT
        r = self.c.patch('/api/company/gst-settings/', {'lut_number': '', 'lut_valid_from': '', 'lut_valid_to': ''},
                         format='json')
        self.assertEqual((r.status_code, r.data['lut_number'], r.data['lut_valid_to']), (200, '', None))

    def test_bad_lut_and_other_fields_are_refused(self):
        # a LUT number without the dates it covers
        r = self.c.patch('/api/company/gst-settings/', {'lut_number': 'AD290326000009Z', 'lut_valid_from': ''},
                         format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('lut_number', r.data)
        r = self.c.patch('/api/company/gst-settings/', {'company_name': 'New'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_members_can_read_but_not_change(self):
        member = User.objects.create_user(username='m3', email='m3@e.com', password='pw-123456')
        member.user_company = self.company
        member.save()
        c = APIClient()
        c.force_authenticate(member)
        r = c.get('/api/company/gst-settings/')
        self.assertEqual((r.status_code, r.data['can_edit'], r.data['company_gst_number']), (200, False, SELLER))
        self.assertEqual(c.patch('/api/company/gst-settings/', {'gst_filing_frequency': 'quarterly'},
                                 format='json').status_code, 403)


class SetOffTests(SimpleTestCase):

    def test_igst_credit_covers_the_shortfall_first(self):
        used, cash, left = set_off({'igst': D(0), 'cgst': D(100), 'sgst': D(100)},
                                   {'igst': D(150), 'cgst': D(0), 'sgst': D(100)})
        self.assertEqual((used[('igst', 'cgst')], used[('igst', 'sgst')], used[('sgst', 'sgst')]),
                         (D(100), D(50), D(50)))
        self.assertEqual((sum(cash.values()), left['sgst']), (D(0), D(50)))

    def test_cgst_credit_never_pays_sgst(self):
        _, cash, left = set_off({'igst': D(0), 'cgst': D(0), 'sgst': D(100)},
                                {'igst': D(0), 'cgst': D(100), 'sgst': D(0)})
        self.assertEqual((cash['sgst'], left['cgst']), (D(100), D(100)))


class QuarterlyTests(Base):

    def setUp(self):
        super().setUp()
        self.company.gst_filing_frequency = 'quarterly'
        self.company.save()
        cache.clear()
        self.reg = Customers.objects.create(user=self.user, name='Reg', gst_number=MH_GSTIN, state_code=27)
        self.walkin = Customers.objects.create(user=self.user, name='Walk-in', state_code=29)

    def test_first_month_is_the_iff(self):
        self.invoice('S-1', [self.line()], self.reg)
        self.invoice('S-2', [self.line(hsn='')], self.walkin)       # B2C with a problem: not in the IFF
        with frozen(2026, 11, 17):
            d = self.get('/api/gstr1/', period='last_month')
            res = self.c.get('/api/gstr1/', {'period': 'last_month', 'download': 1})
        self.assertEqual((d['return_type'], d['ready_to_file']), ('IFF', True))
        self.assertEqual(res.status_code, 200)
        self.assertIn('IFF_', res['Content-Disposition'])
        f = json.loads(res.content)
        self.assertEqual(set(f), {'gstin', 'fp', 'b2b'})
        self.assertEqual(f['fp'], '102026')

    def test_third_month_is_refused(self):
        with frozen(2026, 12, 10):
            r = self.c.get('/api/gstr1/', {'period': 'this_month'})
        self.assertEqual((r.status_code, r.data['code']), (400, 'quarterly_third_month'))

    def test_quarter_leaves_out_b2b_sent_in_the_iff(self):
        self.invoice('S-1', [self.line()], self.reg, date=datetime.date(2026, 7, 5))      # IFF month
        self.invoice('S-2', [self.line()], self.reg, date=datetime.date(2026, 9, 5))      # quarter-end month
        self.invoice('S-3', [self.line()], self.walkin, date=datetime.date(2026, 7, 6))   # B2C: quarterly only
        with frozen(2026, 10, 15):
            d = self.get('/api/gstr1/', period='last_quarter')
            full = self.get('/api/gstr1/', period='last_quarter', include_iff=1)
        b2b = lambda data: next(t for t in data['tables'] if t['table'] == 'b2b')['count']
        b2cs = lambda data: next(t for t in data['tables'] if t['table'] == 'b2cs')['count']
        self.assertEqual((d['iff_months_left_out'], b2b(d), b2cs(d)), (True, 1, 1))
        self.assertEqual((full['iff_months_left_out'], b2b(full)), (False, 2))


class Gstr9Tests(Base):

    def test_annual_tables(self):
        reg = Customers.objects.create(user=self.user, name='Reg', gst_number=MH_GSTIN, state_code=27)
        walkin = Customers.objects.create(user=self.user, name='Walk-in', state_code=29)
        abroad = Customers.objects.create(user=self.user, name='US', gst_treatment='overseas', state_code=96)
        inv = self.invoice('S-1', [self.line()], reg)
        self.invoice('S-2', [self.line(rate='500')], walkin, date=datetime.date(2027, 1, 5))
        self.invoice('S-3', [self.line(rate='2000', gst='0')], abroad)
        self.invoice('S-4', [self.line(rate='300', gst='0', category='exempt')], walkin)
        CreditDebitNote.objects.create(user=self.user, customer=reg, invoice=inv, note_type='credit',
                                       note_number='CN-1', amount=D('118'), gst_amount=D('18'), date=self.oct)
        v = Vendor.objects.create(user=self.user, name='KA', gst_number=KA_GSTIN, state_code=29)
        self.invoice('P-1', [self.line()], v, inv_type='purchase', itc_eligibility='blocked')
        self.invoice('S-OLD', [self.line()], reg, date=datetime.date(2026, 3, 31))        # previous FY

        d = self.get('/api/gstr9/', fy=2026)
        t4, t5, t6, t7 = rows(d['table4']), rows(d['table5']), rows(d['table6']), rows(d['table7'])
        self.assertEqual((t4['4A']['taxable'], t4['4A']['cgst']), (500.0, 45.0))
        self.assertEqual((t4['4B']['taxable'], t4['4B']['igst']), (1000.0, 180.0))
        self.assertEqual((t4['4I']['taxable'], t4['4I']['igst']), (100.0, 18.0))
        self.assertEqual((t4['4N']['taxable'], t4['4N']['igst']), (1400.0, 162.0))
        self.assertEqual((t5['5A']['taxable'], t5['5D']['taxable'], t5['5N']['taxable']), (2000.0, 300.0, 2300.0))
        self.assertEqual((t6['6A']['cgst'], t7['7E']['cgst'], d['net_itc']['cgst']), (90.0, 90.0, 0.0))
        self.assertEqual({r['hsn'] for r in d['table17']}, {'8471'})
        self.assertEqual(d['fy_label'], 'FY 2026-27')

    def test_fy_must_be_valid(self):
        self.assertEqual(self.c.get('/api/gstr9/', {'fy': 'abc'}).status_code, 400)
        self.assertEqual(self.c.get('/api/gstr9/', {'fy': 2090}).status_code, 400)
