"""The invoice list must cost a fixed number of queries, however many invoices
and line items are on the page (it used to be N+1 on user/customer/vendor/
products/properties)."""
import datetime
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from accounts.authz_seed import ensure_company_roles
from accounts.models import CompanyPermission, CompanyRole, User, UserCompanies
from companies.models import (CompanySubscription, Customers, SubscriptionPlan)
from invoice.models import (Invoice, Product, Product_properties,
                            new_product_in_frontend)


class InvoiceListQueryCountTests(APITestCase):

    def setUp(self):
        cache.clear()
        self.company = UserCompanies.objects.create(company_name='Acme', is_varified=True)
        self.admin = User.objects.create_user(username='boss', password='x12345678')
        self.admin.user_company = self.company
        self.admin.is_company_admin = True
        self.admin.save()
        role, _ = ensure_company_roles(CompanyRole, CompanyPermission, self.company)
        role.users.add(self.admin)
        plan = SubscriptionPlan.objects.create(
            name='Basic Test', code='basic_test', monthly_price=1, yearly_price=10)
        today = timezone.now().date()
        CompanySubscription.objects.create(
            company=self.company, subscription_plan=plan, start_date=today,
            end_date=today + timedelta(days=30), status='active')
        self.cols = [new_product_in_frontend.objects.create(
            user=self.admin, input_title=t, size=1) for t in ('Item', 'Qty', 'Rate')]

    def make_invoices(self, n, lines=3):
        for i in range(n):
            cust = Customers.objects.create(name=f'Cust {i}', user=self.admin)
            inv = Invoice.objects.create(
                user=self.admin, receiver=cust, date=datetime.date.today(),
                total_final_amount=Decimal('100'), payment_status='unpaid',
                invoice_type='sales')
            for _ in range(lines):
                p = Product.objects.create(gst_amount=1, total_amount=10)
                for c in self.cols:
                    p.product_properties.add(Product_properties.objects.create(
                        new_product_in_frontend=c, value='x'))
                inv.products.add(p)

    def count(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        with CaptureQueriesContext(connection) as ctx:
            r = client.get('/api/invoice/?invoice_type=sales&ordering=-date&page_size=50')
        self.assertEqual(r.status_code, 200)
        return len(ctx), r.data

    def test_query_count_does_not_grow_with_page_size(self):
        self.make_invoices(2)
        self.count()                # warm the per-company caches
        small, _ = self.count()
        self.make_invoices(18)
        large, data = self.count()
        print(f'\nQUERIES: 2 invoices={small}, 20 invoices={large}')
        self.assertEqual(len(data['results']), 20)
        self.assertEqual(small, large)


class InvoiceUpdateBlankHeaderFieldsTests(InvoiceListQueryCountTests):
    """The web editor posts FormData; untouched optional fields arrive blank."""

    def test_blank_due_date_and_place_of_supply_save_as_null(self):
        self.make_invoices(1, lines=1)
        inv = Invoice.objects.get()
        client = APIClient()
        client.force_authenticate(user=self.admin)
        for blank in ('', 'null', 'undefined'):
            r = client.post(f'/api/invoice/{inv.id}/update/',
                            {'due_date': blank, 'place_of_supply': blank,
                             'payment_status': 'paid'}, format='multipart')
            self.assertEqual(r.status_code, 200, (blank, r.data))
            inv.refresh_from_db()
            self.assertIsNone(inv.due_date)
            self.assertIsNone(inv.place_of_supply)
            self.assertEqual(inv.payment_status, 'paid')

    def test_real_values_still_validate(self):
        self.make_invoices(1, lines=1)
        inv = Invoice.objects.get()
        client = APIClient()
        client.force_authenticate(user=self.admin)
        r = client.post(f'/api/invoice/{inv.id}/update/',
                        {'due_date': 'garbage'}, format='multipart')
        self.assertEqual(r.status_code, 400)
        r = client.post(f'/api/invoice/{inv.id}/update/',
                        {'due_date': '2026-11-30', 'place_of_supply': '27'}, format='multipart')
        self.assertEqual(r.status_code, 200, r.data)
