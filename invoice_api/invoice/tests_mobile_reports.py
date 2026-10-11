"""Contract tests for what MobileApp/services/{reports,purchases}.ts read from the API."""
import datetime
import uuid
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.authz_seed import ensure_company_roles
from accounts.models import CompanyPermission, CompanyRole, UserCompanies
from companies.models import Customers, Vendor
from invoice.models import Invoice, InvoiceExtractionLog
from invoice.tests_numbering import give_plan

User = get_user_model()


class MobileReportsContractTest(TestCase):
    def setUp(self):
        cache.clear()   # plan/feature lookups are cached per company id, and ids repeat across tests
        company = UserCompanies.objects.create(
            company_name='Acme', is_varified=True, state_code=27)
        self.user = User.objects.create_user(username='rep', email='r@e.com', password='x')
        self.user.user_company = company
        self.user.is_company_admin = True
        self.user.save()
        give_plan(company, ['invoicing', 'advanced_reports', 'purchases_invoice', 'bulk_export', 'ocr_purchase_invoice'],
                  limits={'ocr_purchase_invoice': {'ocr_scans_per_month': 5}})
        admin_role, _ = ensure_company_roles(CompanyRole, CompanyPermission, company)
        admin_role.users.add(self.user)

        self.cust = Customers.objects.create(name='Buyer', user=self.user, state='Maharashtra', state_code=27)
        self.vendor = Vendor.objects.create(name='Supplier', user=self.user)
        today = datetime.date.today()
        self.sale = Invoice.objects.create(user=self.user, receiver=self.cust, date=today, invoice_number='S1',
                                           total_final_amount=1180, gst_final_amount=180, payment_status='paid',
                                           payment_method='upi')
        self.bill = Invoice.objects.create(user=self.user, vendor=self.vendor, date=today, invoice_number='B1',
                                           invoice_type='purchase', total_final_amount=590, gst_final_amount=90)
        self.c = APIClient()
        self.c.force_authenticate(user=self.user)

    def test_sales_report_shape(self):
        d = self.c.get('/api/sales-report/').data
        for k in ('total_sales', 'total_invoices', 'paid_amount', 'unpaid_amount', 'overdue_amount',
                  'average_invoice_value', 'gst_collected', 'top_customer', 'highest_sale_day', 'sales_growth_pct',
                  'credit_notes_issued', 'credit_notes_amount'):
            self.assertIn(k, d['summary'], k)
        for k in ('sales_trend', 'payment_status_distribution', 'top_customers', 'sales_by_state',
                  'payment_method_distribution'):
            self.assertIsInstance(d['charts'][k], list, k)
        self.assertEqual(d['summary']['total_sales'], 1180.0)       # purchases are not sales
        self.assertEqual(d['charts']['top_customers'][0], {'name': 'Buyer', 'sales': 1180.0})
        self.assertIn('new_customers', d['kpis'])
        self.assertIn('repeat_customer_pct', d['kpis'])

    def test_cash_flow_shape_and_range(self):
        today = datetime.date.today()
        rows = self.c.get('/api/cash-flow/', {'start_date': (today - datetime.timedelta(days=6)).isoformat(),
                                              'end_date': today.isoformat(), 'interval': 'daily'}).data
        self.assertEqual(len(rows), 7)
        last = rows[-1]
        self.assertEqual((last['inflow'], last['outflow'], last['net']), (1180.0, 590.0, 590.0))

    def test_gst_summary_shape(self):
        d = self.c.get('/api/gst-summary/', {'period': 'this_fy'}).data
        for k in ('period_label', 'start_date', 'end_date', 'total_sales_taxable', 'total_purchases_taxable',
                  'output_gst', 'input_gst', 'net_gst_payable', 'sales_invoice_count', 'purchase_invoice_count'):
            self.assertIn(k, d, k)
        for k in ('cgst', 'sgst', 'igst', 'unclassified', 'unclassified_invoices'):
            self.assertIn(k, d['tax_split'], k)
        self.assertEqual(d['output_gst'], 180)
        self.assertEqual(d['input_gst'], 90)

    def test_ledger_shape_for_customer_and_vendor(self):
        for kind, party in (('customer', self.cust), ('vendor', self.vendor)):
            d = self.c.get(f'/api/ledger/{kind}/{party.id}/', {'period': 'all_time'}).data
            for k in ('opening_balance', 'closing_balance', 'transactions', 'outstanding_total', 'outstanding_count',
                      'ageing', 'open_invoices', 'lifetime', 'period_label', 'party'):
                self.assertIn(k, d, f'{kind}:{k}')
            self.assertEqual(d['party']['name'], party.name)
            for k in ('billed', 'settled'):
                self.assertIn(k, d['lifetime'])
            for t in d['transactions']:
                for k in ('date', 'vch_type', 'debit', 'credit', 'balance'):
                    self.assertIn(k, t)
        # the unpaid purchase bill shows up as an open payable
        v = self.c.get(f'/api/ledger/vendor/{self.vendor.id}/', {'period': 'all_time'}).data
        self.assertEqual(v['outstanding_count'], 1)
        self.assertEqual({'id', 'invoice_number', 'billed', 'paid', 'due', 'age_days'} - set(v['open_invoices'][0]), set())
        self.assertEqual({'label', 'amount', 'count'} - set(v['ageing'][0]), set())

    def test_purchase_list_and_default_sales_list_are_separate(self):
        sales = self.c.get('/api/invoice/', {'invoice_type': 'sales'}).data['results']
        buys = self.c.get('/api/invoice/', {'invoice_type': 'purchase'}).data['results']
        self.assertEqual([i['invoice_number'] for i in sales], ['S1'])
        self.assertEqual([i['invoice_number'] for i in buys], ['B1'])
        self.assertEqual(buys[0]['vendor_name'], 'Supplier')
        self.assertIn('vendor_gst_number', buys[0])

    def test_create_purchase_bill_with_vendor_json(self):
        res = self.c.post('/api/invoice/', {
            'vendor': self.vendor.id, 'date': '2026-10-01', 'invoice_type': 'purchase',
            'payment_status': 'unpaid', 'invoice_number': 'V-77',
            'total_final_amount': '118.00', 'gst_final_amount': '18.00'}, format='json')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.data['vendor_name'], 'Supplier')
        self.assertEqual(res.data['invoice_number'], 'V-77')   # purchases keep the vendor's own number

    def test_csv_export_by_range_and_type(self):
        today = datetime.date.today().isoformat()
        res = self.c.post('/api/bulk_export/', {'type': 'CSV', 'date_from': today, 'date_to': today,
                                                'invoice_type': 'purchase'}, format='json')
        self.assertEqual(res.status_code, 200)
        body = res.content.decode()
        self.assertIn('B1', body)
        self.assertNotIn('S1', body)

    @mock.patch('invoice.api.pipline.requests.post')
    def test_ocr_upload_multipart_and_jobs(self, post):
        job = str(uuid.uuid4())
        post.return_value = mock.Mock(status_code=202, text='', json=lambda: {'job_id': job, 'status': 'queued'})
        res = self.c.post('/api/purchase/upload/', {
            'file': SimpleUploadedFile('bill-1.jpg', b'\xff\xd8\xff fake', content_type='image/jpeg'),
            'invoice_type': 'purchase'}, format='multipart')
        self.assertEqual(res.status_code, 202, res.content)
        self.assertEqual(res.data['job_id'], job)
        self.assertEqual(InvoiceExtractionLog.objects.count(), 1)

        # same filename again is refused as a duplicate (the app names camera shots uniquely)
        dup = self.c.post('/api/purchase/upload/', {
            'file': SimpleUploadedFile('bill-1.jpg', b'x', content_type='image/jpeg')}, format='multipart')
        self.assertEqual(dup.status_code, 400)

        d = self.c.get('/api/purchase/ocr-jobs/').data
        self.assertEqual(set(d['usage']) >= {'this_month', 'monthly_limit', 'today', 'daily_limit', 'total'}, True)
        self.assertEqual(d['usage']['monthly_limit'], 5)
        self.assertEqual(d['counts']['processing'], 1)
        j = d['jobs'][0]
        for k in ('id', 'job_id', 'file_name', 'status', 'state', 'created_at', 'extracted'):
            self.assertIn(k, j, k)
        self.assertEqual(j['state'], 'processing')
        for k in ('invoice_number', 'date', 'vendor_name', 'total_amount', 'gst_amount'):
            self.assertIn(k, j['extracted'], k)
