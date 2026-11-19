"""E-way bills, Phase A: verdict, validity, checks, bulk JSON, API and PDF fields."""
import datetime
import json
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import AuditLog
from companies.models import CompanySubscription, Customers, Feature, PlanFeature
from invoice import eway
from invoice.models import EwayBill
from invoice.serializers import InvoiceSerializerForPDF
from invoice.tests_gst_phase3 import KA_GSTIN, MH_GSTIN, Base

User = get_user_model()
IST = eway.IST
TRANSPORTER = MH_GSTIN          # any valid GSTIN works as a transporter ID


class RuleTests(SimpleTestCase):

    def test_validity_days_end_at_midnight(self):
        at = datetime.datetime(2026, 11, 5, 10, 0, tzinfo=IST)
        self.assertEqual(eway.validity_until(at, 150), datetime.datetime(2026, 11, 6, 23, 59, 59, tzinfo=IST))
        self.assertEqual(eway.validity_until(at, 200).date(), datetime.date(2026, 11, 6))
        self.assertEqual(eway.validity_until(at, 201).date(), datetime.date(2026, 11, 7))
        # over-dimensional cargo: 20 km a day
        self.assertEqual(eway.validity_until(at, 25, 'O').date(), datetime.date(2026, 11, 7))
        self.assertIsNone(eway.validity_until(at, 0))

    def test_validity_uses_indian_date(self):
        # 20:00 UTC on the 5th is 01:30 IST on the 6th
        at = datetime.datetime(2026, 11, 5, 20, 0, tzinfo=datetime.timezone.utc)
        self.assertEqual(eway.validity_until(at, 100).date(), datetime.date(2026, 11, 7))

    def test_vehicle_numbers(self):
        for ok in ('KA01AB1234', 'ka 01 ab 1234', 'MH-12-A-1234', 'DL1C1234', 'ABC1234', '22BH1234AB',
                   'TR01AB1234567'):
            self.assertIsNone(eway.vehicle_error(ok), ok)
        for bad in ('KA01', '1234', 'KAAB1234X'):
            self.assertIsNotNone(eway.vehicle_error(bad), bad)

    def test_transporter_id(self):
        self.assertIsNone(eway.transporter_id_error(TRANSPORTER))
        self.assertIsNotNone(eway.transporter_id_error(TRANSPORTER[:-1] + 'A'))
        self.assertIsNotNone(eway.transporter_id_error('ABC'))

    def test_pin_state(self):
        self.assertTrue(eway.pin_matches_state('560001', 29))
        self.assertFalse(eway.pin_matches_state('400001', 29))
        self.assertTrue(eway.pin_matches_state('403001', 30))     # Goa shares the 40 zone


class EwayBase(Base):

    def setUp(self):
        super().setUp()
        sub = CompanySubscription.objects.get(company=self.company)
        # Tests below mock timezone.now to fixed dates; keep the plan active on them.
        CompanySubscription.objects.filter(pk=sub.pk).update(start_date=datetime.date(2026, 1, 1))
        plan = sub.subscription_plan
        feat, _ = Feature.objects.get_or_create(code='eway_bill', defaults={'name': 'E-way Bills'})
        PlanFeature.objects.get_or_create(subscription_plan=plan, feature=feat)
        self.company.pincode, self.company.city = '560001', 'Bengaluru'
        self.company.company_address = '12 MG Road'
        self.company.save()
        cache.clear()
        self.today = timezone.localdate()
        self.mh = Customers.objects.create(user=self.user, name='Buyer MH', gst_number=MH_GSTIN,
                                           gst_treatment='registered', state_code=27, pincode='400001',
                                           address='1 Marine Drive', city='Mumbai')
        self.ka = Customers.objects.create(user=self.user, name='Buyer KA', gst_number=KA_GSTIN,
                                           gst_treatment='registered', state_code=29, pincode='560034',
                                           address='Koramangala', city='Bengaluru')

    def sale(self, number='E-1', lines=None, party=None, **kw):
        kw.setdefault('date', self.today)
        return self.invoice(number, lines or [self.line(rate='60000')], party or self.ka, **kw)

    def put(self, inv, **data):
        r = self.c.put(f'/api/eway/{inv.id}/', data, format='json')
        self.assertEqual(r.status_code, 200, getattr(r, 'data', r.content))
        return r.data

    def codes(self, issues, level='error'):
        return {i['code'] for i in issues if i['level'] == level}


class VerdictTests(EwayBase):

    def v(self, inv):
        return eway.verdict(inv, self.company)

    def test_limit_is_more_than_50000(self):
        self.assertFalse(self.v(self.sale('A', [self.line(rate='50000', gst='0')]))['needed'])
        self.assertTrue(self.v(self.sale('B', [self.line(rate='50001', gst='0')]))['needed'])
        # tax counts towards the value: 45,000 + 18% = 53,100
        self.assertTrue(self.v(self.sale('C', [self.line(rate='45000')]))['needed'])

    def test_services_and_exempt_goods_do_not_count(self):
        self.assertEqual(self.v(self.sale('S', [self.line(rate='90000', hsn='998314')]))['code'], 'services')
        mixed = self.sale('M', [self.line(rate='40000'),                       # 47,200
                                self.line(rate='30000', gst='0', category='exempt'),
                                self.line(rate='30000', hsn='998314')])
        self.assertEqual(self.v(mixed)['consignment_value'], 47200.0)
        self.assertFalse(self.v(mixed)['needed'])

    def test_purchase_is_not_ours(self):
        inv = self.invoice('P', [self.line(rate='90000')], inv_type='purchase', date=self.today)
        self.assertEqual(self.v(inv)['code'], 'purchase')

    def test_state_override_for_intra_state(self):
        intra = self.sale('I', [self.line(rate='60000', gst='0')], self.ka)
        inter = self.sale('X', [self.line(rate='60000', gst='0')], self.mh)
        with mock.patch.dict(eway.INTRA_STATE_LIMITS, {29: Decimal('100000')}):
            self.assertFalse(self.v(intra)['needed'])
            self.assertTrue(self.v(inter)['needed'])


class BillTests(EwayBase):

    def test_new_invoice_lists_what_is_missing(self):
        self.company.pincode = ''
        self.company.save()
        cache.clear()
        data = self.get(f'/api/eway/{self.sale().id}/')
        self.assertFalse(data['saved'])
        self.assertTrue(data['verdict']['needed'])
        self.assertEqual(self.codes(data['issues']), {'company_pincode', 'part_b'})
        self.assertFalse(data['ready'])

    def test_intra_state_file(self):
        inv = self.sale('E-1', [self.line(rate='30000', Quantity='2')])       # 60,000 + 18%
        data = self.put(inv, vehicle_number='ka 01 ab 1234', distance_km=12)
        self.assertTrue(data['ready'], data['issues'])
        self.assertEqual(data['eway_bill']['vehicle_number'], 'KA01AB1234')

        r = self.c.get('/api/eway/json/', {'ids': str(inv.id), 'download': '1'})
        self.assertEqual(r.status_code, 200, getattr(r, 'data', None))
        self.assertIn('EWB_bulk_', r['Content-Disposition'])
        body = json.loads(r.content)
        self.assertEqual(body['version'], eway.BULK_VERSION)
        bill, = body['billLists']
        self.assertEqual((bill['supplyType'], bill['subSupplyType'], bill['docType'], bill['transType']),
                         ('O', 1, 'INV', 1))
        self.assertEqual(bill['docNo'], 'E-1')
        self.assertEqual(bill['docDate'], self.today.strftime('%d/%m/%Y'))
        self.assertEqual((bill['fromGstin'], bill['fromPincode'], bill['fromStateCode']), (self.company.company_gst_number, 560001, 29))
        self.assertEqual(bill['fromPlace'], 'Bengaluru')
        self.assertEqual((bill['toGstin'], bill['toPincode'], bill['toStateCode'], bill['actualToStateCode']),
                         (KA_GSTIN, 560034, 29, 29))
        self.assertEqual((bill['totalValue'], bill['cgstValue'], bill['sgstValue'], bill['igstValue']),
                         (60000.0, 5400.0, 5400.0, 0.0))
        self.assertEqual(bill['totInvValue'], 70800.0)
        self.assertEqual((bill['transMode'], bill['transDistance'], bill['vehicleNo'], bill['vehicleType']),
                         (1, 12, 'KA01AB1234', 'R'))
        item, = bill['itemList']
        self.assertEqual((item['hsnCode'], item['quantity'], item['cgstRate'], item['igstRate']),
                         (8471, 2.0, 9, 0))
        self.assertEqual(bill['mainHsnCode'], 8471)

    def test_inter_state_ship_to_and_services_in_other_value(self):
        inv = self.sale('E-2', [self.line(rate='60000'), self.line(rate='1000', hsn='996511')], self.mh)
        self.put(inv, transporter_id=TRANSPORTER, ship_to_address='Plot 4, MIDC', ship_to_place='Pune',
                 ship_to_state_code=27, ship_to_pincode='411019')
        bill = eway.Bill(EwayBill.objects.get(invoice=inv).invoice, self.company)
        self.assertEqual(bill.issues, [])
        e = bill.entry
        self.assertEqual((e['transType'], e['toGstin'], e['toPincode'], e['toPlace']),
                         (2, MH_GSTIN, 411019, 'Pune'))
        self.assertEqual((e['igstValue'], e['cgstValue']), (10800.0, 0.0))
        self.assertEqual(len(e['itemList']), 1)                 # the freight line is a service
        self.assertEqual(e['OthValue'], 1180.0)
        self.assertEqual(e['totInvValue'], 71980.0)
        self.assertEqual((e['vehicleNo'], e['transporterId']), ('', TRANSPORTER))

    def test_export_needs_the_port(self):
        us = Customers.objects.create(user=self.user, name='US buyer', gst_treatment='overseas', state_code=96)
        inv = self.sale('X-1', [self.line(rate='90000', gst='0')], us)
        data = self.put(inv, vehicle_number='KA01AB1234')
        self.assertEqual(data['eway_bill']['sub_supply_type'], 3)
        self.assertIn('export_port', self.codes(data['issues']))
        data = self.put(inv, ship_to_address='Chennai Port', ship_to_place='Chennai',
                        ship_to_state_code=33, ship_to_pincode='600001')
        self.assertTrue(data['ready'], data['issues'])
        e = eway.Bill(inv, self.company).entry
        self.assertEqual((e['toGstin'], e['toStateCode'], e['actualToStateCode']), ('URP', 99, 33))

    def test_errors_block_the_download(self):
        inv = self.sale('E-3', [self.line(rate='60000', hsn='')])
        ok = self.sale('E-4')
        self.put(ok, vehicle_number='KA01AB1234')
        r = self.c.get('/api/eway/json/', {'ids': f'{inv.id},{ok.id}', 'download': '1'})
        self.assertEqual(r.status_code, 409)
        by_id = {b['invoice_id']: b for b in r.data['bills']}
        self.assertFalse(by_id[inv.id]['ready'])
        self.assertIn('hsn_missing', self.codes(by_id[inv.id]['issues']))
        self.assertTrue(by_id[ok.id]['ready'])

    def test_rail_needs_document_and_old_invoice_refused(self):
        inv = self.sale('E-5', date=self.today - datetime.timedelta(days=200))
        data = self.put(inv, transport_mode=2)
        self.assertTrue({'part_b', 'doc_too_old'} <= self.codes(data['issues']))

    def test_unregistered_buyer_and_under_limit_warning(self):
        walkin = Customers.objects.create(user=self.user, name='Walk-in', state_code=29, pincode='560001')
        inv = self.sale('E-6', [self.line(rate='1000')], walkin)
        data = self.put(inv, vehicle_number='KA01AB1234')
        self.assertTrue(data['ready'])
        self.assertIn('under_limit', self.codes(data['issues'], 'warning'))
        self.assertEqual(eway.Bill(inv, self.company).entry['toGstin'], 'URP')

    def test_bad_input_rejected(self):
        inv = self.sale()
        for field, value in [('vehicle_number', 'KA01'), ('ship_to_pincode', '12'),
                             ('transporter_id', 'ABC'), ('ewb_number', '123'), ('distance_km', 5000)]:
            r = self.c.put(f'/api/eway/{inv.id}/', {field: value}, format='json')
            self.assertEqual(r.status_code, 400, field)
            self.assertIn(field, r.data)


class GeneratedTests(EwayBase):

    def test_saving_the_number_sets_validity_and_prints(self):
        inv = self.sale()
        with mock.patch('django.utils.timezone.now',
                        return_value=datetime.datetime(2026, 11, 17, 4, 30, tzinfo=datetime.timezone.utc)):
            data = self.put(inv, vehicle_number='KA01AB1234', distance_km=450, ewb_number='3310 0123 4567')
        ewb = data['eway_bill']
        self.assertEqual((ewb['status'], ewb['ewb_number']), ('generated', '331001234567'))
        # 10:00 IST on the 17th, 450 km = 3 days → end of the 20th
        self.assertTrue(ewb['valid_until'].startswith('2026-11-20T23:59:59'))
        self.assertIn('already_generated', self.codes(data['issues']))

        inv.refresh_from_db()
        pdf = InvoiceSerializerForPDF(inv).data
        self.assertEqual(pdf['eway_bill_number'], '331001234567')
        self.assertEqual(pdf['eway_vehicle_number'], 'KA01AB1234')
        self.assertEqual(pdf['eway_bill_line'],
                         'E-way bill 331001234567 dt. 17/11/2026 · Vehicle KA01AB1234 · valid till 20/11/2026')

        self.assertEqual(AuditLog.objects.filter(resource_type='EWAY_BILL', resource_id=str(inv.id)).count(), 1)

        # cancelled on the portal: no longer printed, and the invoice is pending again
        self.put(inv, status='cancelled')
        inv.refresh_from_db()
        self.assertEqual(InvoiceSerializerForPDF(inv).data['eway_bill_number'], '')
        pending = self.get('/api/eway/pending/')
        self.assertIn(inv.id, [r['invoice_id'] for r in pending['invoices']])

    def test_pdf_blank_without_eway_bill(self):
        self.assertEqual(InvoiceSerializerForPDF(self.sale()).data['eway_bill_line'], '')

    def test_pending_list(self):
        need = self.sale('N-1')
        small = self.sale('N-2', [self.line(rate='100')])
        done = self.sale('N-3')
        self.put(done, vehicle_number='KA01AB1234', ewb_number='331001234568')
        ids = [r['invoice_id'] for r in self.get('/api/eway/pending/')['invoices']]
        self.assertIn(need.id, ids)
        self.assertNotIn(small.id, ids)
        self.assertNotIn(done.id, ids)


class GateTests(EwayBase):

    def test_plan_without_feature_is_refused(self):
        PlanFeature.objects.filter(feature__code='eway_bill').delete()
        cache.clear()
        r = self.c.get(f'/api/eway/{self.sale().id}/')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data.get('code'), 'upgrade_required')

    def test_other_company_invoice_not_found(self):
        from accounts.models import UserCompanies
        other_co = UserCompanies.objects.create(company_name='Other', state_code=29)
        other = User.objects.create_user(username='o', email='o@e.com', password='pw-123456')
        other.user_company = other_co
        other.save()
        inv = self.invoice('O-1', [self.line(rate='60000')], None, date=self.today)
        inv.user = other
        inv.save()
        self.assertEqual(self.c.get(f'/api/eway/{inv.id}/').status_code, 404)
        self.assertEqual(self.c.put(f'/api/eway/{inv.id}/', {}, format='json').status_code, 404)


class DispatchSettingsTests(EwayBase):

    def test_pin_and_city_through_gst_settings(self):
        r = self.c.patch('/api/company/gst-settings/', {'pincode': '560002', 'city': 'Bangalore'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual((r.data['pincode'], r.data['city']), ('560002', 'Bangalore'))
        r = self.c.patch('/api/company/gst-settings/', {'pincode': '05600'}, format='json')
        self.assertEqual(r.status_code, 400)


class EwayToggleTests(EwayBase):
    """`enable_eway_bill` only hides e-way bills from the apps; it defaults on and saved rows are kept."""

    def test_on_by_default_and_reported_in_access(self):
        self.assertTrue(self.c.get('/api/company/gst-settings/').data['enable_eway_bill'])
        self.assertTrue(self.c.get('/api/authz/me/').data['eway_bill_enabled'])

    def test_switch_off_through_gst_settings(self):
        r = self.c.patch('/api/company/gst-settings/', {'enable_eway_bill': False}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertFalse(r.data['enable_eway_bill'])
        self.assertFalse(self.c.get('/api/authz/me/').data['eway_bill_enabled'])
