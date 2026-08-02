"""
Regression tests for the GST summary.

The bug these exist to prevent is subtle and expensive: the report used a
rolling 30-day window, which *coincidentally* equalled the July filing
period on 2 Aug 2026 and then silently stopped equalling it on 17 Aug —
four days before GSTR-3B was due. A number that is right until the moment
you rely on it is worse than one that is visibly wrong, so periods are now
calendar months and the rolling window is gone.

Also covered: place-of-supply split (and its refusal to guess), whole-rupee
rounding, date validation that used to 500, and the data-quality warnings.
"""
from datetime import date
from decimal import Decimal

from django.test import TestCase

from invoice_api.gst import (data_quality, gst_period_bounds,
                             is_valid_state_code, rupees, split_tax)

TODAY = date(2026, 8, 2)


class PeriodTests(TestCase):

    def test_periods_are_calendar_months(self):
        self.assertEqual(gst_period_bounds('this_month', TODAY)[:2],
                         (date(2026, 8, 1), date(2026, 8, 31)))
        s, e, label = gst_period_bounds('last_month', TODAY)
        self.assertEqual((s, e), (date(2026, 7, 1), date(2026, 7, 31)))
        self.assertEqual(label, 'July 2026')

    def test_february_leap_year(self):
        self.assertEqual(gst_period_bounds('this_month', date(2024, 2, 5))[:2],
                         (date(2024, 2, 1), date(2024, 2, 29)))

    def test_quarters_follow_the_indian_financial_year(self):
        # Apr-Jun, Jul-Sep, Oct-Dec, Jan-Mar
        cases = {
            date(2026, 5, 9): (date(2026, 4, 1), date(2026, 6, 30)),
            date(2026, 8, 2): (date(2026, 7, 1), date(2026, 9, 30)),
            date(2026, 11, 9): (date(2026, 10, 1), date(2026, 12, 31)),
            date(2026, 2, 10): (date(2026, 1, 1), date(2026, 3, 31)),
        }
        for today, expected in cases.items():
            self.assertEqual(gst_period_bounds('this_quarter', today)[:2],
                             expected, msg=f'quarter for {today}')

    def test_previous_quarter_crosses_the_year_boundary(self):
        self.assertEqual(gst_period_bounds('last_quarter', date(2026, 12, 9))[:2],
                         (date(2026, 7, 1), date(2026, 9, 30)))

    def test_financial_year(self):
        self.assertEqual(gst_period_bounds('this_fy', TODAY)[:2],
                         (date(2026, 4, 1), date(2027, 3, 31)))
        self.assertEqual(gst_period_bounds('this_fy', date(2026, 2, 1))[:2],
                         (date(2025, 4, 1), date(2026, 3, 31)))


class StateCodeTests(TestCase):

    def test_invalid_codes_rejected(self):
        # 786 is what was actually stored on a live company record
        for bad in (786, '76', None, '', 0, 39, 'MH', -1):
            self.assertFalse(is_valid_state_code(bad), msg=repr(bad))

    def test_valid_codes_accepted(self):
        for good in ('09', 9, 27, 1, 38, 97, 99):
            self.assertTrue(is_valid_state_code(good), msg=repr(good))


class RoundingTests(TestCase):

    def test_whole_rupees_half_up(self):
        self.assertEqual(rupees(113161.54), 113162)
        self.assertEqual(rupees(0.5), 1)
        self.assertEqual(rupees(1.49), 1)
        self.assertEqual(rupees(None), 0)

    def test_negative_rounds_away_from_zero(self):
        self.assertEqual(rupees(-2.5), -3)


class _Row:
    """Stand-in for the values_list rows split_tax consumes."""
    def __init__(self, rows):
        self._rows = rows

    def values_list(self, *_args):
        return self._rows


class SplitTaxTests(TestCase):
    """Place of supply: intra-state → CGST+SGST, inter-state → IGST."""

    HOME = 27   # Maharashtra

    def split(self, rows, home=HOME):
        return split_tax(_Row(rows), home)

    def test_intra_state_halves_into_cgst_and_sgst(self):
        r = self.split([(27, Decimal('1180'), Decimal('180'))])
        self.assertEqual(r['cgst'], Decimal('90'))
        self.assertEqual(r['sgst'], Decimal('90'))
        self.assertEqual(r['igst'], Decimal('0'))
        self.assertEqual(r['intra_taxable'], Decimal('1000'))

    def test_inter_state_is_igst(self):
        r = self.split([('09', Decimal('1180'), Decimal('180'))])
        self.assertEqual(r['igst'], Decimal('180'))
        self.assertEqual(r['cgst'], Decimal('0'))
        self.assertEqual(r['inter_taxable'], Decimal('1000'))

    def test_odd_amounts_still_sum_exactly(self):
        # ₹0.01 must not vanish into a rounding crack between the halves
        r = self.split([(27, Decimal('1000.01'), Decimal('45.01'))])
        self.assertEqual(r['cgst'] + r['sgst'], Decimal('45.01'))

    def test_missing_customer_state_is_unclassified_not_guessed(self):
        r = self.split([(None, Decimal('1180'), Decimal('180'))])
        self.assertEqual(r['unclassified'], Decimal('180'))
        self.assertEqual(r['unclassified_invoices'], 1)
        self.assertEqual(r['cgst'], Decimal('0'))
        self.assertEqual(r['igst'], Decimal('0'))

    def test_invalid_home_state_unclassifies_everything(self):
        # a company whose own state_code is 786 cannot classify anything
        r = self.split([(27, Decimal('1180'), Decimal('180')),
                        ('09', Decimal('1180'), Decimal('180'))], home=786)
        self.assertEqual(r['unclassified'], Decimal('360'))
        self.assertEqual(r['unclassified_invoices'], 2)

    def test_split_reconciles_to_total_output_tax(self):
        rows = [
            (27, Decimal('1180'), Decimal('180')),     # intra
            ('09', Decimal('2360'), Decimal('360')),   # inter
            (None, Decimal('1180'), Decimal('180')),   # unknown
        ]
        r = self.split(rows)
        total = r['cgst'] + r['sgst'] + r['igst'] + r['unclassified']
        self.assertEqual(total, Decimal('720'))

    def test_null_amounts_do_not_crash(self):
        r = self.split([(27, None, None)])
        self.assertEqual(r['cgst'], Decimal('0'))


class DataQualityTests(TestCase):
    """Warnings must fire — a GST report that looks complete gets filed."""

    class FakeCompany:
        def __init__(self, code):
            self.state_code = code

    class FakeQs:
        """Minimal queryset stand-in for the counting the checks do."""
        model = None

        def __init__(self, count=0, total=0):
            self._count, self._total = count, total

        def filter(self, *a, **k):
            return self

        def count(self):
            return self._count

        def aggregate(self, **k):
            return {'v': self._total}

    def issues_for(self, company_code, split_overrides=None, purchase_qs=None):
        split = {
            'unclassified': Decimal('0'), 'unclassified_invoices': 0,
            **(split_overrides or {}),
        }
        empty = self.FakeQs()
        return {i['code']: i for i in data_quality(
            self.FakeCompany(company_code), empty,
            purchase_qs or empty, split, TODAY)}

    def test_invalid_company_state_code_is_an_error(self):
        issues = self.issues_for(786)
        self.assertIn('company_state_code', issues)
        self.assertEqual(issues['company_state_code']['level'], 'error')
        self.assertIn('786', issues['company_state_code']['detail'])

    def test_valid_company_state_code_raises_nothing(self):
        self.assertNotIn('company_state_code', self.issues_for(27))

    def test_unclassified_invoices_are_reported(self):
        issues = self.issues_for(27, {'unclassified': Decimal('113162'),
                                      'unclassified_invoices': 11})
        self.assertIn('customer_state_code', issues)
        self.assertIn('11 invoice', issues['customer_state_code']['title'])

    def test_purchases_without_gst_are_reported(self):
        issues = self.issues_for(27, purchase_qs=self.FakeQs(count=3, total=67393))
        self.assertIn('purchases_without_gst', issues)
        self.assertIn('67,393', issues['purchases_without_gst']['detail'])
