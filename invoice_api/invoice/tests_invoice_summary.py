"""
The numbers above the Invoices list, and the per-row balance fields.

Definitions are the dashboard's (`invoice_api.dashboard`): an invoice is open
while it is unpaid / partially paid / overdue and still has a balance, and it
is overdue if its status says so or it is open and older than
OVERDUE_AFTER_DAYS. These tests lock in the ways that quietly go wrong:
soft-deleted and other-company invoices leaking in, a partial payment counting
as the whole bill, and counts that ignore the filters the tab list applies.
"""
import datetime
from datetime import timedelta
from decimal import Decimal

from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from accounts.authz_seed import ensure_company_roles
from accounts.models import CompanyPermission, CompanyRole, User, UserCompanies
from companies.models import (CompanySubscription, Customers, Feature, PlanFeature,
                              SubscriptionPlan)
from invoice.models import Invoice, Payment


class InvoiceSummaryTests(APITestCase):

    def setUp(self):
        cache.clear()
        self.company = UserCompanies.objects.create(company_name='Acme', is_varified=True)
        self.admin = User.objects.create_user(username='boss', password='x12345678')
        self.admin.user_company = self.company
        self.admin.is_company_admin = True
        self.admin.save()
        role, _ = ensure_company_roles(CompanyRole, CompanyPermission, self.company)
        role.users.add(self.admin)
        self.plan = plan = SubscriptionPlan.objects.create(
            name='Basic Test', code='basic_test', monthly_price=1, yearly_price=10)
        today = timezone.now().date()
        CompanySubscription.objects.create(
            company=self.company, subscription_plan=plan, start_date=today,
            end_date=today + timedelta(days=30), status='active')

        # the same clock the views and the dashboard use (local date, not UTC)
        self.today = datetime.date.today()
        self.month_start = self.today.replace(day=1)
        self.nova = Customers.objects.create(name='Nova Textiles', user=self.admin)
        self.blue = Customers.objects.create(name='Blue Orchid', user=self.admin)

        self.recent = self.invoice(1000, self.month_start, 'unpaid', self.nova)
        self.old = self.invoice(2000, self.today - timedelta(days=45), 'unpaid', self.nova)
        self.partial = self.invoice(3000, self.month_start, 'partially_paid', self.blue)
        Payment.objects.create(user=self.admin, invoice=self.partial, customer=self.blue,
                               amount=Decimal('1000'), payment_type='received',
                               date=self.month_start)
        self.paid = self.invoice(500, self.month_start, 'paid', self.blue)

        # none of these may appear in anything below
        self.invoice(9000, self.month_start, 'unpaid', self.nova).delete()      # soft-deleted
        self.invoice(7000, self.month_start, 'unpaid', None, invoice_type='purchase')
        rival_co = UserCompanies.objects.create(company_name='Rival', is_varified=True)
        rival = User.objects.create_user(username='rival', password='x12345678')
        rival.user_company = rival_co
        rival.save()
        theirs = Customers.objects.create(name='Theirs', user=rival)
        self.invoice(4242, self.month_start, 'unpaid', theirs, user=rival)

    def invoice(self, amount, when, status, customer, invoice_type='sales', user=None):
        return Invoice.objects.create(
            user=user or self.admin, receiver=customer, date=when,
            total_final_amount=Decimal(str(amount)), payment_status=status,
            invoice_type=invoice_type)

    def get(self, url):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        return client.get(url)

    # summary -----------------------------------------------------------

    def test_headline_numbers(self):
        d = self.get('/api/invoice/summary/?invoice_type=sales').data
        self.assertEqual(d['billed_this_month'], 4500.0)        # 1000 + 3000 + 500
        # a part-paid bill contributes only what is left on it
        self.assertEqual(d['awaiting_amount'], 5000)            # 1000 + 2000 + (3000 - 1000)
        self.assertEqual(d['awaiting_count'], 3)
        self.assertEqual(d['overdue_amount'], 2000)             # only the 45-day-old bill
        self.assertEqual(d['overdue_count'], 1)
        self.assertEqual(d['settled_this_month'], 1000.0)

    def test_counts_per_status(self):
        c = self.get('/api/invoice/summary/?invoice_type=sales').data['counts']
        self.assertEqual(c, {'all': 4, 'unpaid': 2, 'partially_paid': 1, 'paid': 1, 'overdue': 1})

    def test_counts_follow_search_and_customer_filters(self):
        c = self.get('/api/invoice/summary/?invoice_type=sales&s=Nova').data['counts']
        self.assertEqual((c['all'], c['unpaid'], c['paid'], c['overdue']), (2, 2, 0, 1))
        c = self.get(f'/api/invoice/summary/?invoice_type=sales&customer={self.blue.id}').data['counts']
        self.assertEqual((c['all'], c['partially_paid'], c['paid'], c['overdue']), (2, 1, 1, 0))

    def test_headline_numbers_ignore_the_filters(self):
        d = self.get('/api/invoice/summary/?invoice_type=sales&s=Nova').data
        self.assertEqual(d['awaiting_amount'], 5000)

    def test_purchase_tab_is_separate(self):
        d = self.get('/api/invoice/summary/?invoice_type=purchase').data
        self.assertEqual(d['counts']['all'], 1)
        self.assertEqual(d['awaiting_amount'], 7000)

    def test_rejects_unknown_type(self):
        self.assertEqual(self.get('/api/invoice/summary/?invoice_type=other').status_code, 400)

    def test_requires_login(self):
        self.assertIn(APIClient().get('/api/invoice/summary/').status_code, (401, 403))

    # list rows ---------------------------------------------------------

    def rows(self, query=''):
        data = self.get(f'/api/invoice/?invoice_type=sales{query}').data
        return {r['id']: r for r in data['results']}

    def test_rows_carry_balance_overdue_and_age(self):
        rows = self.rows()
        self.assertEqual(rows[self.recent.id]['balance_due'], 1000.0)
        self.assertFalse(rows[self.recent.id]['is_overdue'])
        self.assertEqual(rows[self.partial.id]['balance_due'], 2000.0)
        self.assertEqual(rows[self.paid.id]['balance_due'], 0.0)
        self.assertTrue(rows[self.old.id]['is_overdue'])
        self.assertEqual(rows[self.old.id]['age_days'], 45)
        self.assertFalse(rows[self.paid.id]['is_overdue'])

    def test_overdue_tab_list_matches_its_count(self):
        ids = set(self.rows('&status_group=overdue'))
        self.assertEqual(ids, {self.old.id})

    def test_purchase_invoices_are_searchable_by_vendor_name(self):
        from companies.models import Vendor
        vendor = Vendor.objects.create(name='Steel Supplies', user=self.admin)
        bill = self.invoice(500, self.month_start, 'unpaid', None, invoice_type='purchase')
        bill.vendor = vendor
        bill.save()
        data = self.get('/api/invoice/?invoice_type=purchase&s=Steel').data
        self.assertEqual([r['id'] for r in data['results']], [bill.id])

    # purchase page -----------------------------------------------------

    def test_purchase_page_rows_carry_status_and_balance(self):
        # `purchase-summary` feeds the Purchase page; its recent rows show what is
        # still owed on each bill, with the same definitions as the invoice list
        feat, _ = Feature.objects.get_or_create(
            code='purchases_invoice', defaults={'name': 'Purchase invoices'})
        PlanFeature.objects.create(subscription_plan=self.plan, feature=feat)
        cache.clear()
        # the setUp purchase bill (7000, unpaid) plus a paid one and a part-paid one
        paid = self.invoice(500, self.month_start, 'paid', None, invoice_type='purchase')
        part = self.invoice(900, self.month_start, 'partially_paid', None, invoice_type='purchase')
        Payment.objects.create(user=self.admin, invoice=part, amount=Decimal('400'),
                               payment_type='made', date=self.month_start)

        data = self.get('/api/purchase-summary/').data
        rows = {r['id']: r for r in data['recent_purchases']}
        self.assertEqual(rows[paid.id]['balance_due'], 0.0)
        self.assertEqual(rows[paid.id]['payment_status'], 'paid')
        self.assertEqual(rows[part.id]['balance_due'], 500.0)        # 900 minus the 400 paid out
        self.assertFalse(rows[part.id]['is_overdue'])
        # sales invoices never appear on the purchase page
        self.assertTrue(all(self.invoice_type_of(i) == 'purchase' for i in rows))

    def invoice_type_of(self, pk):
        return Invoice.objects.get(pk=pk).invoice_type
