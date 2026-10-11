"""Server-side plan + permission gates on every report, export and OCR endpoint.

The mobile app hides these screens for plans that lack the feature, but hiding is
cosmetic: these tests pin down that the API itself refuses a raw HTTP client.
"""
import uuid

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient

from accounts.authz_seed import ensure_company_roles
from accounts.models import CompanyPermission, CompanyRole, UserCompanies
from companies.models import Customers
from invoice.models import Invoice
from invoice.tests_numbering import give_plan

User = get_user_model()

REPORT_GETS = [
    '/api/sales-report/',
    '/api/cash-flow/',
    '/api/gst-summary/',
    '/api/ledger/customer/1/',
]
PURCHASE_GETS = [
    '/api/purchase-summary/',
    '/api/purchase/ocr-jobs/',
    '/api/purchase/pending-jobs/',
    f'/api/purchase/status/{uuid.uuid4()}/',
]


def make_user(company, username, role_index=None, admin=False):
    u = User.objects.create_user(username=username, email=f'{username}@e.com', password='x')
    u.user_company = company
    u.is_company_admin = admin
    u.save()
    if role_index is not None:
        roles = ensure_company_roles(CompanyRole, CompanyPermission, company)
        roles[role_index].users.add(u)
    return u


def client_for(user):
    c = APIClient()
    c.force_authenticate(user=user)
    return c


class ReportGateTests(TestCase):
    def setUp(self):
        cache.clear()   # plan/feature lookups are cached per company id, and ids repeat across tests
        self.free = UserCompanies.objects.create(company_name='Free Co', is_varified=True)
        give_plan(self.free, ['invoicing'])
        self.free_admin = make_user(self.free, 'freeadmin', role_index=0, admin=True)

        self.pro = UserCompanies.objects.create(company_name='Pro Co', is_varified=True)
        give_plan(self.pro, ['invoicing', 'advanced_reports', 'purchases_invoice', 'bulk_export'])
        self.pro_admin = make_user(self.pro, 'proadmin', role_index=0, admin=True)
        self.pro_member = make_user(self.pro, 'promember', role_index=1)
        self.pro_roleless = make_user(self.pro, 'proroleless')   # no role => no permissions

    def assertUpgrade(self, res, url):
        self.assertEqual(res.status_code, 403, f'{url} -> {res.status_code}')
        self.assertEqual(res.data.get('code'), 'upgrade_required', url)

    # ── plan gate ────────────────────────────────────────────────────────────

    def test_free_plan_blocked_from_reports(self):
        c = client_for(self.free_admin)
        for url in REPORT_GETS:
            self.assertUpgrade(c.get(url), url)

    def test_free_plan_blocked_from_purchases_and_ocr(self):
        c = client_for(self.free_admin)
        for url in PURCHASE_GETS:
            self.assertUpgrade(c.get(url), url)
        self.assertUpgrade(c.post('/api/purchase/upload/', {}, format='multipart'), 'upload')

    def test_free_plan_blocked_from_bulk_export(self):
        self.assertUpgrade(client_for(self.free_admin).post(
            '/api/bulk_export/', {'type': 'CSV'}, format='json'), 'bulk_export')

    def test_pro_plan_reaches_reports(self):
        c = client_for(self.pro_admin)
        for url in ['/api/sales-report/', '/api/cash-flow/', '/api/gst-summary/', '/api/purchase-summary/']:
            self.assertEqual(c.get(url).status_code, 200, url)

    # ── permission gate (plan ok, user lacks the permission) ─────────────────

    def test_user_without_report_view_is_refused_on_pro_plan(self):
        c = client_for(self.pro_roleless)
        for url in REPORT_GETS:
            res = c.get(url)
            self.assertEqual(res.status_code, 403, url)
            self.assertEqual(res.data.get('code'), 'permission_denied', url)

    def test_bulk_export_needs_invoice_view(self):
        res = client_for(self.pro_roleless).post('/api/bulk_export/', {'type': 'CSV'}, format='json')
        self.assertEqual(res.status_code, 403)
        self.assertEqual(res.data.get('code'), 'permission_denied')

    def test_member_with_plan_can_export_csv(self):
        cust = Customers.objects.create(name='C', user=self.pro_admin)
        Invoice.objects.create(user=self.pro_admin, receiver=cust, invoice_number='A1',
                               total_final_amount=100, gst_final_amount=18)
        res = client_for(self.pro_member).post('/api/bulk_export/', {'type': 'CSV'}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/csv', res['Content-Type'])
        self.assertIn(b'A1', res.content)

    # ── tenant isolation ─────────────────────────────────────────────────────

    def test_ledger_does_not_leak_other_companies_customers(self):
        other = Customers.objects.create(name='Rival customer', user=self.free_admin)
        res = client_for(self.pro_admin).get(f'/api/ledger/customer/{other.id}/')
        self.assertEqual(res.status_code, 404)

    def test_purchase_summary_names_the_vendor(self):
        from companies.models import Vendor
        v = Vendor.objects.create(name='Acme Supplies', user=self.pro_admin)
        Invoice.objects.create(user=self.pro_admin, vendor=v, invoice_type='purchase',
                               invoice_number='P1', total_final_amount=50, gst_final_amount=9)
        data = client_for(self.pro_admin).get('/api/purchase-summary/').data
        self.assertEqual(data['recent_purchases'][0]['vendor_name'], 'Acme Supplies')
