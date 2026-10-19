"""
Due date and place of supply on the invoice.

Two things here can quietly go wrong. A due date before the invoice date is
nonsense that autosave would otherwise store, and a place of supply the GST
split ignores would let the invoice say one thing while the return says
another. So: validation on partial updates (the client may send only one of
the two dates), and the split must prefer the invoice's own place of supply
over the customer's registered state, falling back to it when unset.
"""
import datetime
from decimal import Decimal

from django.http import QueryDict
from django.test import TestCase

from accounts.models import User
from companies.models import Customers
from invoice.models import Invoice
from invoice.serializers import InvoiceSerializer
from invoice_api.gst import split_tax

HOME = 23  # Madhya Pradesh


def make_invoice(user, customer, *, place_of_supply=None, gst='180.00', total='1180.00'):
    return Invoice.objects.create(
        user=user, receiver=customer, invoice_type='sales',
        gst_final_amount=Decimal(gst), total_final_amount=Decimal(total),
        date=datetime.date(2026, 8, 1), place_of_supply=place_of_supply)


class PlaceOfSupplySplitTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='seller', password='x12345678')
        self.local = Customers.objects.create(name='Local', user=self.user, state_code=23)
        self.far = Customers.objects.create(name='Far', user=self.user, state_code=27)
        self.nostate = Customers.objects.create(name='No state', user=self.user)

    def split(self):
        return split_tax(Invoice.objects.filter(invoice_type='sales'), HOME)

    def test_unset_place_of_supply_falls_back_to_customer_state(self):
        make_invoice(self.user, self.local)
        make_invoice(self.user, self.far)
        s = self.split()
        self.assertEqual((s['cgst'], s['sgst']), (Decimal('90.00'), Decimal('90.00')))
        self.assertEqual(s['igst'], Decimal('180.00'))

    def test_invoice_place_of_supply_overrides_customer_state(self):
        # customer is local, but this supply is delivered to Maharashtra
        make_invoice(self.user, self.local, place_of_supply=27)
        s = self.split()
        self.assertEqual(s['igst'], Decimal('180.00'))
        self.assertEqual(s['cgst'], Decimal('0'))

    def test_place_of_supply_classifies_a_customer_with_no_state(self):
        make_invoice(self.user, self.nostate, place_of_supply=23)
        s = self.split()
        self.assertEqual(s['unclassified_invoices'], 0)
        self.assertEqual(s['cgst'] + s['sgst'], Decimal('180.00'))

    def test_neither_set_stays_unclassified(self):
        make_invoice(self.user, self.nostate)
        s = self.split()
        self.assertEqual(s['unclassified_invoices'], 1)
        self.assertEqual(s['unclassified'], Decimal('180.00'))


class InvoiceDatesValidationTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user(username='seller', password='x12345678')
        self.invoice = Invoice.objects.create(
            user=self.user, date=datetime.date(2026, 8, 10),
            due_date=datetime.date(2026, 8, 25))

    def check(self, data, instance=None):
        s = InvoiceSerializer(instance, data=data, partial=True)
        return s.is_valid(), s.errors

    def test_due_before_invoice_date_is_rejected(self):
        ok, errors = self.check({'date': '2026-08-10', 'due_date': '2026-08-09'})
        self.assertFalse(ok)
        self.assertIn('due_date', errors)

    def test_due_on_invoice_date_is_allowed(self):
        ok, _ = self.check({'date': '2026-08-10', 'due_date': '2026-08-10'})
        self.assertTrue(ok)

    def test_partial_update_compares_against_the_stored_date(self):
        ok, errors = self.check({'due_date': '2026-08-01'}, self.invoice)
        self.assertFalse(ok)
        self.assertIn('due_date', errors)

    def test_moving_the_date_past_the_stored_due_date_is_rejected(self):
        ok, errors = self.check({'date': '2026-09-01'}, self.invoice)
        self.assertFalse(ok)
        self.assertIn('due_date', errors)

    def test_due_date_and_place_of_supply_can_be_cleared(self):
        # the web editor sends multipart FormData, where '' means "clear"
        form = QueryDict(mutable=True)
        form.update({'due_date': '', 'place_of_supply': ''})
        ok, errors = self.check(form, self.invoice)
        self.assertTrue(ok, errors)
        # JSON clients send null
        ok, errors = self.check({'due_date': None, 'place_of_supply': None}, self.invoice)
        self.assertTrue(ok, errors)

    def test_invalid_state_code_is_rejected(self):
        for bad in (0, 40, 98):
            ok, errors = self.check({'place_of_supply': bad})
            self.assertFalse(ok, bad)
            self.assertIn('place_of_supply', errors)

    def test_valid_state_codes_are_accepted(self):
        for good in (1, 23, 38, 97, 99):
            ok, errors = self.check({'place_of_supply': good})
            self.assertTrue(ok, (good, errors))


class EditorResponseTests(TestCase):
    """What the bill editor gets back from each autosave."""

    def setUp(self):
        from django.core.cache import cache
        from django.utils import timezone
        from rest_framework.test import APIClient
        from accounts.authz_seed import ensure_company_roles
        from accounts.models import CompanyPermission, CompanyRole, UserCompanies
        from companies.models import CompanySubscription, SubscriptionPlan
        from invoice.models import Payment

        cache.clear()
        self.company = UserCompanies.objects.create(
            company_name='Acme', is_varified=True, state_code=23)
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
            end_date=today + datetime.timedelta(days=30), status='active')
        self.customer = Customers.objects.create(name='Nova', user=self.admin, state_code=27)
        self.invoice = Invoice.objects.create(
            user=self.admin, receiver=self.customer, date=today,
            total_final_amount=Decimal('1000'), gst_final_amount=Decimal('152.54'),
            payment_status='partially_paid')
        Payment.objects.create(user=self.admin, invoice=self.invoice, customer=self.customer,
                               amount=Decimal('400'), payment_type='received', date=today)
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)

    def test_update_response_carries_balance_due(self):
        r = self.client.post(f'/api/invoice/{self.invoice.id}/update/', {'terms': 'Net 15'},
                             format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['balance_due'], 600.0)

    def test_notes_terms_place_of_supply_and_due_date_round_trip(self):
        r = self.client.post(
            f'/api/invoice/{self.invoice.id}/update/',
            {'customer_notes': 'Thanks!', 'terms': 'Pay within 15 days',
             'place_of_supply': 23, 'due_date': str(self.invoice.date)},
            format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.invoice.refresh_from_db()
        self.assertEqual((self.invoice.customer_notes, self.invoice.terms, self.invoice.place_of_supply),
                         ('Thanks!', 'Pay within 15 days', 23))
        self.assertEqual(r.data['receiver_state_code'], 27)

    def test_notes_and_terms_can_be_cleared(self):
        Invoice.objects.filter(pk=self.invoice.pk).update(customer_notes='x', terms='y')
        r = self.client.post(f'/api/invoice/{self.invoice.id}/update/',
                             {'customer_notes': '', 'terms': ''}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.invoice.refresh_from_db()
        self.assertEqual((self.invoice.customer_notes, self.invoice.terms), ('', ''))

    def test_a_due_date_before_the_invoice_date_is_a_400(self):
        r = self.client.post(f'/api/invoice/{self.invoice.id}/update/',
                             {'due_date': '2000-01-01'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('due_date', r.data)

    def test_access_payload_carries_the_company_state_code(self):
        r = self.client.get('/api/authz/me/')
        self.assertEqual(r.status_code, 200, r.data)
        self.assertEqual(r.data['company_state_code'], 23)
