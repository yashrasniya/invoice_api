"""
Tests for the per-customer billing stats on the Customers list.

The numbers here are the ones a user reads off the Customers page before
deciding who to chase, so the things worth locking down are the ways a
reverse-FK aggregate quietly lies:

- soft-deleted invoices still exist in the table, and `SoftDeleteModel`
  sets `base_manager_name = 'all_objects'`, so a reverse join sees them
- `Invoice` has an M2M to `Product`; a carelessly built query multiplies
  the Sum by the number of line items (the bug the dashboard shipped with)
- purchase bills are not turnover, and must not count toward a customer's
  total the way they don't in the customer ledger
- another tenant's invoices must never reach this customer's row

Plus the plan gating: the stats are an `advanced_reports` add-on, but the
list itself is what every customer dropdown in the app reads, so a caller
without the feature must still get their customers back.
"""
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from accounts.authz_seed import ensure_company_roles
from accounts.models import (CompanyPermission, CompanyRole, User,
                             UserCompanies)
from companies.api.views import annotate_customer_stats
from companies.models import (CompanySubscription, Customers, Feature,
                              PlanFeature, SubscriptionPlan)
from invoice.models import Invoice, Product


class CustomerStatsAnnotationTests(APITestCase):

    def setUp(self):
        cache.clear()
        self.company = UserCompanies.objects.create(company_name='Acme',
                                                    is_varified=True)
        self.other = UserCompanies.objects.create(company_name='Rival',
                                                  is_varified=True)
        self.user = User.objects.create_user(username='me', password='x12345678')
        self.user.user_company = self.company
        self.user.save()
        self.rival = User.objects.create_user(username='them', password='x12345678')
        self.rival.user_company = self.other
        self.rival.save()

        self.big = Customers.objects.create(name='Big Co', user=self.user)
        self.quiet = Customers.objects.create(name='Quiet Co', user=self.user)

        # several line items per invoice — the Sum fan-out trap
        self.products = [
            Product.objects.create(gst_amount=Decimal('1'),
                                   total_amount=Decimal('1'))
            for _ in range(3)
        ]

        # ── what Big Co should add up to: 3 bills, ₹6,000, last 2026-08-01 ──
        self.invoice(1000, date(2026, 6, 1))
        self.invoice(2000, date(2026, 7, 1))
        self.invoice(3000, date(2026, 8, 1))
        # a NULL amount counts as a bill but adds nothing
        self.invoice(None, date(2026, 7, 15))
        # ── and what must stay out of the total ──
        self.deleted = self.invoice(50000, date(2026, 8, 2))
        self.deleted.delete()                                   # soft delete
        self.invoice(9999, date(2026, 8, 2), invoice_type='purchase')
        self.invoice(7777, date(2026, 8, 3), user=self.rival)   # other tenant

    # helpers ----------------------------------------------------------

    def invoice(self, total, when, customer=None, user=None,
                invoice_type='sales'):
        inv = Invoice.objects.create(
            user=user or self.user,
            receiver=customer or self.big,
            date=when,
            total_final_amount=total,
            gst_final_amount=None,
            invoice_type=invoice_type,
        )
        inv.products.set(self.products)
        return inv

    def stats_for(self, customer, user=None):
        user = user or self.user
        request = SimpleNamespace(company=user.user_company, user=user)
        return (annotate_customer_stats(Customers.objects.all(), request)
                .get(id=customer.id))

    # tests ------------------------------------------------------------

    def test_counts_and_totals_only_this_customers_sales(self):
        row = self.stats_for(self.big)
        # 3 priced bills + 1 with a NULL amount; the soft-deleted, purchase
        # and cross-tenant bills are all excluded
        self.assertEqual(row.invoice_count, 4)
        self.assertEqual(Decimal(row.total_billed), Decimal('6000'))

    def test_line_items_do_not_multiply_the_total(self):
        # 3 products per invoice: a fanned-out join would report ₹18,000
        self.assertEqual(Decimal(self.stats_for(self.big).total_billed),
                         Decimal('6000'))

    def test_last_invoice_date_ignores_excluded_bills(self):
        # the newest sales bill is 2026-08-01; the soft-deleted (08-02),
        # purchase (08-02) and rival (08-03) bills are all later
        self.assertEqual(self.stats_for(self.big).last_invoice_date,
                         date(2026, 8, 1))

    def test_customer_with_no_bills_reads_zero_not_null(self):
        row = self.stats_for(self.quiet)
        self.assertEqual(row.invoice_count, 0)
        self.assertEqual(Decimal(row.total_billed), Decimal('0'))
        self.assertIsNone(row.last_invoice_date)

    def test_restoring_a_deleted_invoice_puts_it_back_in_the_total(self):
        self.deleted.restore()
        row = self.stats_for(self.big)
        self.assertEqual(row.invoice_count, 5)
        self.assertEqual(Decimal(row.total_billed), Decimal('56000'))

    def test_other_company_sees_none_of_this(self):
        # the rival's own bill points at Big Co, but Big Co isn't their
        # customer — and scoping the join means they can't total it either
        rival_view = self.stats_for(self.big, user=self.rival)
        self.assertEqual(rival_view.invoice_count, 1)
        self.assertEqual(Decimal(rival_view.total_billed), Decimal('7777'))


class CustomerStatsEndpointTests(APITestCase):
    """`GET /api/companies/?with_stats=1` and its plan gating."""

    def setUp(self):
        cache.clear()
        self.company = UserCompanies.objects.create(company_name='Acme',
                                                    is_varified=True)
        self.admin = User.objects.create_user(username='boss',
                                              password='x12345678')
        self.admin.user_company = self.company
        self.admin.is_company_admin = True
        self.admin.save()
        admin_role, _ = ensure_company_roles(
            CompanyRole, CompanyPermission, self.company)
        admin_role.users.add(self.admin)

        self.customer = Customers.objects.create(name='Big Co', user=self.admin)
        Invoice.objects.create(user=self.admin, receiver=self.customer,
                               date=date(2026, 8, 1),
                               total_final_amount=Decimal('1500'),
                               invoice_type='sales')

        self.plan = SubscriptionPlan.objects.create(
            name='Basic Test', code='basic_test', monthly_price=1, yearly_price=10)
        today = timezone.now().date()
        self.sub = CompanySubscription.objects.create(
            company=self.company, subscription_plan=self.plan,
            start_date=today, end_date=today + timedelta(days=30),
            status='active')

    def grant_advanced_reports(self):
        feat, _ = Feature.objects.get_or_create(
            code='advanced_reports', defaults={'name': 'Advanced Reports'})
        PlanFeature.objects.create(subscription_plan=self.plan, feature=feat)
        cache.clear()

    def get(self, url):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        return client.get(url)

    def test_stats_are_absent_unless_asked_for(self):
        # every customer dropdown in the app hits this endpoint; it must not
        # pay for an aggregate join it isn't going to read
        self.grant_advanced_reports()
        row = self.get('/api/companies/').data['results'][0]
        self.assertNotIn('invoice_count', row)

    def test_stats_returned_with_the_feature(self):
        self.grant_advanced_reports()
        row = self.get('/api/companies/?with_stats=1').data['results'][0]
        self.assertEqual(row['invoice_count'], 1)
        self.assertEqual(Decimal(row['total_billed']), Decimal('1500'))
        self.assertEqual(row['last_invoice_date'], '2026-08-01')

    def test_without_the_feature_the_list_still_works(self):
        # degrading to a plain list beats 403-ing the customer dropdowns of
        # everyone on a cheaper plan
        response = self.get('/api/companies/?with_stats=1')
        self.assertEqual(response.status_code, 200)
        row = response.data['results'][0]
        self.assertEqual(row['name'], 'Big Co')
        self.assertNotIn('invoice_count', row)

    def test_search_matches_name_gst_number_and_phone(self):
        # people look customers up by whatever they have to hand. The search
        # query param is `s` here (REST_FRAMEWORK SEARCH_PARAM), not DRF's `search`.
        other = Customers.objects.create(name='Other Co', user=self.admin,
                                         gst_number='27ABCDE1234F1Z5',
                                         phone_number='9876501234')
        def ids(q):
            return [r['id'] for r in self.get(f'/api/companies/?s={q}').data['results']]
        self.assertEqual(ids('Other'), [other.id])
        self.assertEqual(ids('abcde1234f'), [other.id])   # GSTIN, any case
        self.assertEqual(ids('98765'), [other.id])        # part of a phone number
        self.assertEqual(ids('Big'), [self.customer.id])

    def test_state_and_gst_filters(self):
        gst = Customers.objects.create(name='Registered', user=self.admin,
                                       gst_number='27ABCDE1234F1Z5', state='Maharashtra')
        def ids(q):
            return {r['id'] for r in self.get(f'/api/companies/?{q}').data['results']}
        self.assertEqual(ids('has_gst=1'), {gst.id})
        self.assertEqual(ids('has_gst=0'), {self.customer.id})
        self.assertEqual(ids('state=Maharashtra'), {gst.id})
        self.assertEqual(ids('state=Kerala'), set())

    def test_outstanding_balance_matches_the_customer_ledger(self):
        # the list and the ledger must never disagree about what is owed
        from invoice.models import CreditDebitNote, Payment
        self.grant_advanced_reports()
        inv = Invoice.objects.filter(receiver=self.customer).first()   # ₹1,500
        # a receipt against the customer directly, one reaching it only via its invoice
        Payment.objects.create(user=self.admin, customer=self.customer, amount=Decimal('200'),
                               payment_type='received', date=date(2026, 8, 5))
        Payment.objects.create(user=self.admin, invoice=inv, amount=Decimal('100'),
                               payment_type='received', date=date(2026, 8, 6))
        # money paid *to* a customer is not a receipt
        Payment.objects.create(user=self.admin, customer=self.customer, amount=Decimal('999'),
                               payment_type='made', date=date(2026, 8, 7))
        CreditDebitNote.objects.create(user=self.admin, customer=self.customer, amount=Decimal('50'),
                                       note_type='credit', date=date(2026, 8, 8))
        CreditDebitNote.objects.create(user=self.admin, customer=self.customer, amount=Decimal('30'),
                                       note_type='debit', date=date(2026, 8, 9))
        # soft-deleted and purchase invoices must stay out
        Invoice.objects.create(user=self.admin, receiver=self.customer, date=date(2026, 8, 2),
                               total_final_amount=Decimal('8000'), invoice_type='sales').delete()
        Invoice.objects.create(user=self.admin, receiver=self.customer, date=date(2026, 8, 2),
                               total_final_amount=Decimal('7000'), invoice_type='purchase')
        # and another tenant's customer stays at zero
        rival_co = UserCompanies.objects.create(company_name='Rival', is_varified=True)
        rival = User.objects.create_user(username='rival', password='x12345678')
        rival.user_company = rival_co
        rival.save()
        theirs = Customers.objects.create(name='Theirs', user=rival)
        Invoice.objects.create(user=rival, receiver=theirs, date=date(2026, 8, 1),
                               total_final_amount=Decimal('4242'), invoice_type='sales')

        rows = {r['id']: r for r in self.get('/api/companies/?with_stats=1').data['results']}
        expected = Decimal('1500') - 200 - 100 - 50 + 30
        self.assertEqual(Decimal(str(rows[self.customer.id]['outstanding_balance'])), expected)
        self.assertNotIn(theirs.id, rows)

        ledger = self.get(f'/api/ledger/customer/{self.customer.id}/?period=all_time').data
        self.assertEqual(Decimal(str(ledger['closing_balance'])), expected)

    def test_outstanding_balance_absent_without_stats(self):
        row = self.get('/api/companies/').data['results'][0]
        self.assertNotIn('outstanding_balance', row)

    def test_lookup_by_id_for_deep_links(self):
        # the invoice list resolves `?customer=<id>` to a name through this
        other = Customers.objects.create(name='Someone Else', user=self.admin)
        results = self.get(f'/api/companies/?id={self.customer.id}').data['results']
        self.assertEqual([r['id'] for r in results], [self.customer.id])
        self.assertNotIn(other.id, [r['id'] for r in results])
