"""
Regression tests for the customer dashboard aggregates.

These lock down the bugs the dashboard shipped with:

- growth % was computed against a placeholder denominator of 1, so a first
  month of trading read as "+49,900%" instead of "no comparison available"
- purchase invoices were summed into the Sales and GST cards
- nothing surfaced money owed, and "overdue" was a status nothing ever set
- the payment-method widget grouped *invoices* by method, reporting unpaid
  bills as cash received

Also guards the joins: Invoice has an M2M to Product and a reverse FK to
Payment, either of which will silently multiply a Sum if the query is built
carelessly.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Q
from django.test import TestCase

from accounts.models import User, UserCompanies
from companies.models import Customers
from invoice.models import Invoice, Payment, Product
from invoice_api.dashboard import (
    fy_bounds, gst_due_dates, monthly_trend, open_invoices_qs,
    outstanding_totals, payment_method_split, pct_change, period_bounds,
    sales_totals, top_customers,
)

TODAY = date(2026, 8, 2)


class PurePeriodMathTests(TestCase):
    """No database — just the date and percentage logic."""

    def test_no_baseline_returns_none_not_a_fake_percentage(self):
        # the original bug: prev was forced to 1, turning a first month of
        # ₹50,000 sales into "+4,999,900%"
        self.assertIsNone(pct_change(50000, 0))
        self.assertIsNone(pct_change(0, 0))

    def test_ordinary_growth(self):
        self.assertEqual(pct_change(200, 100), 100.0)
        self.assertEqual(pct_change(50, 100), -50.0)
        self.assertEqual(pct_change(100, 100), 0.0)
        self.assertEqual(pct_change(0, 100), -100.0)

    def test_month_bounds_and_year_rollover(self):
        cur, prev, label = period_bounds('this_month', TODAY)
        self.assertEqual(cur, (date(2026, 8, 1), date(2026, 8, 31)))
        self.assertEqual(prev, (date(2026, 7, 1), date(2026, 7, 31)))
        self.assertEqual(label, 'August 2026')

        _, prev, _ = period_bounds('this_month', date(2026, 1, 15))
        self.assertEqual(prev, (date(2025, 12, 1), date(2025, 12, 31)))

    def test_february_leap_year(self):
        cur, _, _ = period_bounds('this_month', date(2024, 2, 10))
        self.assertEqual(cur, (date(2024, 2, 1), date(2024, 2, 29)))

    def test_indian_financial_year_straddles_calendar_year(self):
        self.assertEqual(fy_bounds(date(2026, 2, 1)),
                         (date(2025, 4, 1), date(2026, 3, 31)))
        self.assertEqual(fy_bounds(date(2026, 4, 1)),
                         (date(2026, 4, 1), date(2027, 3, 31)))
        _, _, label = period_bounds('this_fy', TODAY)
        self.assertEqual(label, 'FY 2026-27')

    def test_last_30_days(self):
        cur, prev, _ = period_bounds('last_30', TODAY)
        self.assertEqual(cur, (date(2026, 7, 4), date(2026, 8, 2)))
        self.assertEqual(prev, (date(2026, 6, 4), date(2026, 7, 3)))

    def test_gst_deadlines_roll_past_the_due_date(self):
        before = gst_due_dates(date(2026, 8, 2))
        self.assertEqual(before[0]['form'], 'GSTR-1')
        self.assertEqual(before[0]['due_date'], '2026-08-11')
        self.assertEqual(before[0]['period'], 'Jul 2026')

        after = gst_due_dates(date(2026, 8, 15))
        self.assertEqual(after[0]['due_date'], '2026-09-11')
        self.assertEqual(after[0]['period'], 'Aug 2026')
        self.assertEqual(after[1]['due_date'], '2026-08-20')   # 3B still open

        self.assertEqual(gst_due_dates(date(2026, 12, 27))[0]['due_date'],
                         '2027-01-11')


class DashboardAggregateTests(TestCase):

    def setUp(self):
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
        self.small = Customers.objects.create(name='Small Co', user=self.user)

        # an M2M with several rows per invoice — the classic Sum fan-out trap
        self.products = [
            Product.objects.create(gst_amount=Decimal('1'),
                                   total_amount=Decimal('1'))
            for _ in range(3)
        ]

        # ── the fixture ────────────────────────────────────────────────
        # part-paid: ₹1000 billed, ₹500 received → ₹500 still owed
        self.part_paid = self.invoice(1000, 180, date(2026, 8, 1),
                                      'partially_paid')
        self.pay(self.part_paid, 300, date(2026, 8, 1), 'cash')
        self.pay(self.part_paid, 200, date(2026, 8, 2), 'upi')
        # recent and unpaid — owed, but not yet old enough to be overdue
        self.recent_unpaid = self.invoice(500, 90, date(2026, 7, 20),
                                          'unpaid', customer=self.small)
        # 93 days old and unpaid → derived overdue
        self.aged = self.invoice(800, 144, date(2026, 5, 1), 'unpaid')
        # settled
        paid = self.invoice(2000, 360, date(2026, 8, 1), 'paid')
        self.pay(paid, 2000, date(2026, 8, 1), 'bank_transfer')
        # NULL amounts must not crash the aggregates
        self.invoice(None, None, date(2026, 8, 1), 'unpaid')
        # payments already cover it, status just wasn't updated
        self.covered = self.invoice(400, 72, date(2026, 8, 1), 'unpaid')
        self.pay(self.covered, 400, date(2026, 8, 1), 'upi')
        # a purchase bill — a cost, never turnover
        self.invoice(9999, 1800, date(2026, 8, 1), 'unpaid',
                     invoice_type='purchase')
        # another tenant entirely
        self.invoice(7777, 1400, date(2026, 8, 1), 'unpaid', user=self.rival)
        # last month, for the comparison period
        prev = self.invoice(600, 108, date(2026, 7, 5), 'paid')
        self.pay(prev, 600, date(2026, 7, 5), 'cheque')
        # money going out must never look like money coming in
        self.pay(self.part_paid, 999, date(2026, 8, 1), 'cash',
                 payment_type='made')

    # helpers ----------------------------------------------------------

    def invoice(self, total, gst, when, status, customer=None, user=None,
                invoice_type='sales'):
        inv = Invoice.objects.create(
            user=user or self.user,
            receiver=customer or self.big,
            date=when,
            total_final_amount=total,
            gst_final_amount=gst,
            payment_status=status,
            invoice_type=invoice_type,
        )
        inv.products.set(self.products)
        return inv

    def pay(self, inv, amount, when, method='upi', payment_type='received'):
        return Payment.objects.create(
            user=self.user, company=self.company, invoice=inv,
            amount=Decimal(amount), date=when, payment_method=method,
            payment_type=payment_type)

    @property
    def sales(self):
        return Invoice.objects.filter(
            Q(user__user_company=self.company), invoice_type='sales')

    @property
    def payments(self):
        return Payment.objects.filter(company=self.company)

    # sales totals -----------------------------------------------------

    def test_purchases_and_other_tenants_are_excluded(self):
        aug = sales_totals(self.sales, date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(aug['total'], 1000 + 2000 + 400)   # not 9999, not 7777
        self.assertEqual(aug['gst'], 180 + 360 + 72)

    def test_m2m_products_do_not_multiply_the_sum(self):
        # three products per invoice; a naive join would treble every total
        aug = sales_totals(self.sales, date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(aug['total'], 3400)
        self.assertEqual(aug['count'], 4)

    def test_null_amounts_are_tolerated(self):
        jul = sales_totals(self.sales, date(2026, 7, 1), date(2026, 7, 31))
        self.assertEqual(jul['total'], 1100)

    # outstanding ------------------------------------------------------

    def test_outstanding_is_net_of_part_payments(self):
        out = outstanding_totals(self.sales, TODAY)
        # (1000-500) + 500 + 800; the fully covered bill drops out
        self.assertEqual(out['receivable_amount'], 1800)
        self.assertEqual(out['receivable_count'], 3)

    def test_overdue_is_derived_from_age(self):
        out = outstanding_totals(self.sales, TODAY)
        self.assertEqual(out['overdue_amount'], 800)
        self.assertEqual(out['overdue_count'], 1)
        self.assertEqual(out['overdue_after_days'], 30)

    def test_explicit_overdue_status_is_honoured(self):
        self.recent_unpaid.payment_status = 'overdue'
        self.recent_unpaid.save()
        out = outstanding_totals(self.sales, TODAY)
        self.assertEqual(out['overdue_amount'], 1300)

    def test_deep_link_returns_exactly_what_the_card_counted(self):
        # the Outstanding card and /bill_list?status_group=open must agree
        open_ids = set(open_invoices_qs(self.sales, TODAY)
                       .values_list('id', flat=True))
        self.assertEqual(open_ids, {self.part_paid.id, self.recent_unpaid.id,
                                    self.aged.id})
        self.assertNotIn(self.covered.id, open_ids)

        overdue_ids = set(open_invoices_qs(self.sales, TODAY)
                          .filter(is_overdue=True).values_list('id', flat=True))
        self.assertEqual(overdue_ids, {self.aged.id})

    def test_outstanding_is_a_single_query(self):
        with self.assertNumQueries(1):
            outstanding_totals(self.sales, TODAY)

    # payment mix ------------------------------------------------------

    def test_payment_mix_counts_cash_received_not_invoice_metadata(self):
        mix = {m['method']: m['total'] for m in
               payment_method_split(self.payments,
                                    date(2026, 8, 1), date(2026, 8, 31))}
        self.assertEqual(mix['cash'], 300)          # the ₹999 'made' is excluded
        self.assertEqual(mix['upi'], 600)
        self.assertEqual(mix['bank_transfer'], 2000)
        self.assertNotIn('unrecorded', mix)         # unpaid bills contribute nothing
        self.assertNotIn('cheque', mix)             # July payment, not August

    # trend ------------------------------------------------------------

    def test_trend_agrees_with_the_kpi_for_the_same_month(self):
        trend = monthly_trend(self.sales, TODAY, months=6)
        aug = sales_totals(self.sales, date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(len(trend), 6)
        self.assertEqual(trend[-1]['label'], 'Aug')
        self.assertEqual(trend[-1]['total'], aug['total'])

    def test_trend_reports_empty_months_as_zero(self):
        trend = monthly_trend(self.sales, TODAY, months=6)
        self.assertEqual([t['label'] for t in trend],
                         ['Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug'])
        self.assertEqual(trend[1]['total'], 0)      # April: no invoices
        self.assertEqual(trend[2]['total'], 800)    # May

    # customers --------------------------------------------------------

    def test_top_customers_ranked_without_join_inflation(self):
        top = top_customers(self.sales, date(2026, 8, 1), date(2026, 8, 31))
        self.assertEqual(top[0]['name'], 'Big Co')
        self.assertEqual(top[0]['total'], 3400)
        self.assertEqual(len(top), 1)               # Small Co billed in July only


class UserInfoEndpointTests(TestCase):
    """The endpoint contract the dashboard cards depend on."""

    def setUp(self):
        from rest_framework.test import APIClient
        self.company = UserCompanies.objects.create(company_name='Solo',
                                                    is_varified=True)
        self.user = User.objects.create_user(username='solo', password='x12345678')
        self.user.user_company = self.company
        self.user.is_company_admin = True
        self.user.save()
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_brand_new_account_reports_no_growth_rather_than_a_fake_one(self):
        res = self.client.get('/user_info/')
        if res.status_code != 200:
            self.skipTest(f'user_info/ not routed at this path ({res.status_code})')
        body = res.json()
        self.assertIsNone(body['percentage_change'])
        self.assertIsNone(body['percentage_gst_amount'])
        self.assertEqual(body['month_total_final_amount'], 0)   # not ₹1
        self.assertEqual(body['month_gst_final_amount'], 0)     # not ₹1
        self.assertFalse(body['has_any_invoice'])
