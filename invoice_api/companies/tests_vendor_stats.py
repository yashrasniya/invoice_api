"""
The Vendors page's API: search, filters, the email field, per-vendor purchase
stats, and what we owe each vendor.

What we owe a vendor must equal the closing balance on the supplier ledger
(`/api/ledger/vendor/<id>/`), so the numbers the person reads on the two screens
can never disagree. The things worth locking down are the ways it quietly lies:
soft-deleted and sales invoices leaking in, a payment that reaches the vendor
only through its invoice being missed, and another company's rows.
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
                              SubscriptionPlan, Vendor)
from invoice.models import CreditDebitNote, Invoice, Payment


class VendorApiTests(APITestCase):

    def setUp(self):
        cache.clear()
        self.company = UserCompanies.objects.create(company_name='Acme', is_varified=True)
        self.admin = User.objects.create_user(username='boss', password='x12345678')
        self.admin.user_company = self.company
        self.admin.is_company_admin = True
        self.admin.save()
        role, _ = ensure_company_roles(CompanyRole, CompanyPermission, self.company)
        role.users.add(self.admin)
        self.plan = SubscriptionPlan.objects.create(
            name='Basic Test', code='basic_test', monthly_price=1, yearly_price=10)
        today = timezone.now().date()
        CompanySubscription.objects.create(
            company=self.company, subscription_plan=self.plan, start_date=today,
            end_date=today + timedelta(days=30), status='active')

        self.today = datetime.date.today()
        self.when = self.today.replace(day=1)
        self.steel = Vendor.objects.create(name='Steel Supplies', user=self.admin,
                                           gst_number='27ABCDE1234F1Z5', phone_number='9876501234',
                                           state='Maharashtra', email='sales@steel.example')
        self.paper = Vendor.objects.create(name='Paper Mart', user=self.admin)

    def get(self, url):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        return client.get(url)

    def grant_advanced_reports(self):
        feat, _ = Feature.objects.get_or_create(
            code='advanced_reports', defaults={'name': 'Advanced Reports'})
        PlanFeature.objects.create(subscription_plan=self.plan, feature=feat)
        cache.clear()

    def bill(self, vendor, amount, status='unpaid', invoice_type='purchase', when=None, user=None):
        return Invoice.objects.create(
            user=user or self.admin, vendor=vendor, date=when or self.when,
            total_final_amount=Decimal(str(amount)), payment_status=status,
            invoice_type=invoice_type)

    def ids(self, query):
        return {r['id'] for r in self.get(f'/api/vendors/?{query}').data['results']}

    # list, search, filters --------------------------------------------

    def test_search_matches_name_gst_number_and_phone(self):
        self.assertEqual(self.ids('s=Steel'), {self.steel.id})
        self.assertEqual(self.ids('s=abcde1234f'), {self.steel.id})   # GSTIN, any case
        self.assertEqual(self.ids('s=98765'), {self.steel.id})        # part of a phone number
        self.assertEqual(self.ids('s=Paper'), {self.paper.id})

    def test_gst_state_and_id_filters(self):
        self.assertEqual(self.ids('has_gst=1'), {self.steel.id})
        self.assertEqual(self.ids('has_gst=0'), {self.paper.id})
        self.assertEqual(self.ids('state=Maharashtra'), {self.steel.id})
        self.assertEqual(self.ids(f'id={self.paper.id}'), {self.paper.id})

    def test_email_is_saved_and_returned(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        r = client.post('/api/vendors/', {'name': 'New Co', 'email': 'hi@new.example'}, format='multipart')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['email'], 'hi@new.example')
        rows = {v['name']: v for v in self.get('/api/vendors/').data['results']}
        self.assertEqual(rows['New Co']['email'], 'hi@new.example')
        self.assertEqual(rows['Steel Supplies']['email'], 'sales@steel.example')

    def test_edit_updates_the_vendor(self):
        client = APIClient()
        client.force_authenticate(user=self.admin)
        r = client.post(f'/api/vendors/{self.paper.id}/', {'name': 'Paper Mart Ltd', 'phone_number': '9000000001'},
                        format='multipart')
        self.assertEqual(r.status_code, 200)
        self.paper.refresh_from_db()
        self.assertEqual((self.paper.name, self.paper.phone_number), ('Paper Mart Ltd', '9000000001'))

    def test_other_company_vendors_are_invisible(self):
        rival_co = UserCompanies.objects.create(company_name='Rival', is_varified=True)
        rival = User.objects.create_user(username='rival', password='x12345678')
        rival.user_company = rival_co
        rival.save()
        theirs = Vendor.objects.create(name='Steel Rival', user=rival)
        self.assertNotIn(theirs.id, self.ids('s=Steel'))

    # stats and what we owe --------------------------------------------

    def test_stats_are_absent_without_the_flag_or_the_plan_feature(self):
        self.assertNotIn('outstanding_balance', self.get('/api/vendors/').data['results'][0])
        # asked for, but the plan doesn't carry advanced reports: ignored, list still works
        row = self.get('/api/vendors/?with_stats=1').data['results'][0]
        self.assertNotIn('outstanding_balance', row)
        self.assertNotIn('invoice_count', row)

    def test_purchase_stats_and_balance_match_the_supplier_ledger(self):
        self.grant_advanced_reports()
        first = self.bill(self.steel, 1000)
        self.bill(self.steel, 3000, status='partially_paid', when=self.when + timedelta(days=1))
        # a payment made against the vendor directly, one reaching it only via its invoice
        Payment.objects.create(user=self.admin, vendor=self.steel, amount=Decimal('200'),
                               payment_type='made', date=self.when)
        Payment.objects.create(user=self.admin, invoice=first, amount=Decimal('100'),
                               payment_type='made', date=self.when)
        # money *received* from a vendor is not a payment against what we owe
        Payment.objects.create(user=self.admin, vendor=self.steel, amount=Decimal('999'),
                               payment_type='received', date=self.when)
        # a credit note from the vendor reduces what we owe; a debit note raises it
        CreditDebitNote.objects.create(user=self.admin, vendor=self.steel, amount=Decimal('50'),
                                       note_type='credit', date=self.when)
        CreditDebitNote.objects.create(user=self.admin, vendor=self.steel, amount=Decimal('30'),
                                       note_type='debit', date=self.when)
        # none of these may count
        self.bill(self.steel, 8000).delete()                                   # soft-deleted
        self.bill(self.steel, 7000, invoice_type='sales')                      # a sale, not a purchase
        rival_co = UserCompanies.objects.create(company_name='Rival', is_varified=True)
        rival = User.objects.create_user(username='rival', password='x12345678')
        rival.user_company = rival_co
        rival.save()
        self.bill(self.steel, 4242, user=rival)                                # another company's bill

        rows = {r['id']: r for r in self.get('/api/vendors/?with_stats=1').data['results']}
        steel = rows[self.steel.id]
        self.assertEqual(steel['invoice_count'], 2)
        self.assertEqual(Decimal(str(steel['total_purchased'])), Decimal('4000'))
        self.assertEqual(steel['last_invoice_date'], str(self.when + timedelta(days=1)))
        expected = Decimal('4000') - 200 - 100 - 50 + 30
        self.assertEqual(Decimal(str(steel['outstanding_balance'])), expected)
        self.assertEqual(rows[self.paper.id]['outstanding_balance'], 0)

        ledger = self.get(f'/api/ledger/vendor/{self.steel.id}/?period=all_time').data
        self.assertEqual(Decimal(str(ledger['closing_balance'])), expected)

    # invoice list ------------------------------------------------------

    def test_invoice_list_filters_by_vendor(self):
        a = self.bill(self.steel, 100)
        self.bill(self.paper, 200)
        data = self.get(f'/api/invoice/?invoice_type=purchase&vendor={self.steel.id}').data
        self.assertEqual([r['id'] for r in data['results']], [a.id])
        counts = self.get(f'/api/invoice/summary/?invoice_type=purchase&vendor={self.steel.id}').data['counts']
        self.assertEqual(counts['all'], 1)
