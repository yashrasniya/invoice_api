"""
Per-company invoice header settings: which optional fields show, and which
defaults a new invoice starts with.

The rules that matter: an untouched company behaves exactly as before; a
default never overrides something the user sent; defaults still apply to
fields that are hidden (that is the use case); validation rejects a default
that can't be applied; and only template managers may change the settings.
"""
import datetime
from decimal import Decimal

from django.core.cache import cache
from django.http import QueryDict
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.authz_seed import ensure_company_roles
from accounts.models import CompanyPermission, CompanyRole, User, UserCompanies
from companies.models import CompanySubscription, SubscriptionPlan
from invoice import header_config as hc
from invoice.models import Invoice, InvoiceHeaderConfig

TODAY = datetime.date(2026, 8, 10)


class NormalizeTests(SimpleTestCase):

    def test_untouched_company_shows_everything_and_defaults_nothing(self):
        out = hc.normalize(None)
        self.assertEqual(set(out), set(hc.KEYS))
        for entry in out.values():
            self.assertEqual(entry, {'visible': True, 'use_default': False, 'default': None})

    def test_stored_values_are_merged_over_the_blank_ones(self):
        out = hc.normalize({'payment_method': {'visible': False, 'use_default': True, 'default': 'upi'}})
        self.assertEqual(out['payment_method'], {'visible': False, 'use_default': True, 'default': 'upi'})
        self.assertTrue(out['payment_status']['visible'])

    def test_garbage_in_storage_does_not_break_reads(self):
        self.assertEqual(hc.normalize('nonsense')['terms']['visible'], True)
        self.assertEqual(hc.normalize({'terms': 'x'})['terms']['visible'], True)


class ValidateTests(SimpleTestCase):

    def check(self, incoming, current=None):
        return hc.validate(current, incoming)

    def test_valid_defaults_are_accepted(self):
        out = self.check({
            'place_of_supply': {'use_default': True, 'default': 23},
            'payment_terms': {'use_default': True, 'default': 15},
            'payment_status': {'use_default': True, 'default': 'paid'},
            'payment_method': {'use_default': True, 'default': 'cash'},
            'customer_notes': {'use_default': True, 'default': '  Thanks!  '},
            'terms': {'use_default': True, 'default': 'Net 15'},
        })
        self.assertEqual(out['place_of_supply']['default'], 23)
        self.assertEqual(out['customer_notes']['default'], 'Thanks!')

    def test_a_default_that_cannot_apply_is_rejected(self):
        bad = [
            {'place_of_supply': {'use_default': True, 'default': 99999}},
            {'place_of_supply': {'use_default': True, 'default': None}},
            {'payment_terms': {'use_default': True, 'default': 12}},
            {'payment_status': {'use_default': True, 'default': 'maybe'}},
            {'payment_method': {'use_default': True, 'default': ''}},
            {'terms': {'use_default': True, 'default': '   '}},
            {'terms': {'use_default': True, 'default': 'x' * (hc.MAX_TEXT_LEN + 1)}},
        ]
        for payload in bad:
            with self.assertRaises(ValueError, msg=payload):
                self.check(payload)

    def test_unknown_field_is_an_error(self):
        with self.assertRaises(ValueError):
            self.check({'invoice_number': {'visible': False}})

    def test_hiding_needs_no_default(self):
        out = self.check({'payment_method': {'visible': False}})
        self.assertFalse(out['payment_method']['visible'])
        self.assertFalse(out['payment_method']['use_default'])

    def test_partial_update_keeps_the_other_fields(self):
        first = self.check({'payment_status': {'use_default': True, 'default': 'paid'}})
        second = self.check({'terms': {'visible': False}}, current=first)
        self.assertEqual(second['payment_status']['default'], 'paid')
        self.assertFalse(second['terms']['visible'])

    def test_turning_a_default_off_keeps_the_value_so_it_can_come_back(self):
        on = self.check({'payment_method': {'use_default': True, 'default': 'upi'}})
        off = self.check({'payment_method': {'use_default': False}}, current=on)
        self.assertFalse(off['payment_method']['use_default'])
        self.assertEqual(off['payment_method']['default'], 'upi')

    def test_string_booleans_from_form_posts_are_understood(self):
        out = self.check({'terms': {'visible': 'false'}})
        self.assertFalse(out['terms']['visible'])


class ApplyDefaultsTests(SimpleTestCase):

    CFG = hc.validate(None, {
        'place_of_supply': {'use_default': True, 'default': 27},
        'payment_terms': {'use_default': True, 'default': 15},
        'payment_status': {'use_default': True, 'default': 'paid'},
        'payment_method': {'visible': False, 'use_default': True, 'default': 'cash'},
        'customer_notes': {'use_default': True, 'default': 'Thanks!'},
        'terms': {'use_default': True, 'default': 'Net 15'},
    })

    def apply(self, data, invoice_type='sales', cfg=None):
        return hc.apply_defaults(data, self.CFG if cfg is None else cfg, invoice_type, today=TODAY)

    def test_fills_everything_that_was_left_out(self):
        out = self.apply({'invoice_type': 'sales'})
        self.assertEqual(out['place_of_supply'], 27)
        self.assertEqual(out['payment_status'], 'paid')
        self.assertEqual(out['payment_method'], 'cash')       # hidden fields still default
        self.assertEqual(out['customer_notes'], 'Thanks!')
        self.assertEqual(out['terms'], 'Net 15')
        self.assertEqual(out['due_date'], '2026-08-25')       # today + 15

    def test_due_date_counts_from_the_invoice_date_when_sent(self):
        out = self.apply({'date': '2026-09-01'})
        self.assertEqual(out['due_date'], '2026-09-16')

    def test_what_the_client_sent_wins(self):
        out = self.apply({'payment_status': 'unpaid', 'payment_method': 'card',
                          'place_of_supply': 7, 'due_date': '2026-12-31',
                          'customer_notes': 'Custom', 'terms': 'Mine'})
        self.assertEqual((out['payment_status'], out['payment_method'], out['place_of_supply']),
                         ('unpaid', 'card', 7))
        self.assertEqual(out['due_date'], '2026-12-31')
        self.assertEqual((out['customer_notes'], out['terms']), ('Custom', 'Mine'))

    def test_browser_null_strings_count_as_not_sent(self):
        # FormData.append(k, null) arrives as the string "null"
        out = self.apply({'payment_status': 'null', 'customer_notes': '', 'due_date': 'undefined'})
        self.assertEqual(out['payment_status'], 'paid')
        self.assertEqual(out['customer_notes'], 'Thanks!')
        self.assertEqual(out['due_date'], '2026-08-25')

    def test_place_of_supply_is_not_defaulted_on_purchases(self):
        out = self.apply({'invoice_type': 'purchase'}, invoice_type='purchase')
        self.assertNotIn('place_of_supply', out)
        self.assertEqual(out['payment_status'], 'paid')

    def test_no_settings_changes_nothing(self):
        data = {'invoice_type': 'sales'}
        self.assertEqual(hc.apply_defaults(data, None, 'sales', today=TODAY), data)

    def test_a_default_that_is_switched_off_is_not_applied(self):
        cfg = hc.validate(self.CFG, {'payment_status': {'use_default': False}})
        self.assertNotIn('payment_status', self.apply({}, cfg=cfg))

    def test_works_on_a_multipart_querydict_without_mutating_it(self):
        original = QueryDict('invoice_type=sales')
        out = self.apply(original)
        self.assertEqual(out['payment_status'], 'paid')
        self.assertNotIn('payment_status', original)


class HeaderConfigAPITests(TestCase):

    def setUp(self):
        cache.clear()
        self.company = UserCompanies.objects.create(company_name='Acme', is_varified=True, state_code=23)
        self.admin = self.make_user('boss', admin=True)
        plan = SubscriptionPlan.objects.create(
            name='Basic Test', code='basic_test', monthly_price=1, yearly_price=10)
        today = timezone.now().date()
        CompanySubscription.objects.create(
            company=self.company, subscription_plan=plan, start_date=today,
            end_date=today + datetime.timedelta(days=30), status='active')
        self.role, _ = ensure_company_roles(CompanyRole, CompanyPermission, self.company)
        self.role.users.add(self.admin)

    def make_user(self, name, admin=False):
        user = User.objects.create_user(username=name, password='x12345678')
        user.user_company = self.company
        user.is_company_admin = admin
        user.save()
        return user

    def client_for(self, user):
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_get_returns_everything_shown_for_an_unconfigured_company(self):
        r = self.client_for(self.admin).get('/api/invoice-header-config/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(all(f['visible'] and not f['use_default'] for f in r.data['fields'].values()))
        self.assertEqual([c['key'] for c in r.data['catalog']], hc.KEYS)
        self.assertFalse(InvoiceHeaderConfig.objects.exists())     # reading creates nothing

    def test_save_then_read_back(self):
        c = self.client_for(self.admin)
        r = c.post('/api/invoice-header-config/', {'fields': {
            'payment_method': {'visible': False, 'use_default': True, 'default': 'upi'}}}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        again = c.get('/api/invoice-header-config/').data['fields']['payment_method']
        self.assertEqual(again, {'visible': False, 'use_default': True, 'default': 'upi'})

    def test_invalid_default_is_a_400_with_a_message(self):
        r = self.client_for(self.admin).post('/api/invoice-header-config/', {'fields': {
            'payment_status': {'use_default': True, 'default': 'nope'}}}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('error', r.data)
        self.assertFalse(InvoiceHeaderConfig.objects.exists())

    def test_a_user_without_template_manage_can_read_but_not_save(self):
        member = self.make_user('clerk')
        c = self.client_for(member)
        self.assertEqual(c.get('/api/invoice-header-config/').status_code, 200)
        r = c.post('/api/invoice-header-config/', {'fields': {'terms': {'visible': False}}}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_settings_are_per_company(self):
        self.client_for(self.admin).post('/api/invoice-header-config/', {'fields': {
            'terms': {'visible': False}}}, format='json')
        other_co = UserCompanies.objects.create(company_name='Rival', is_varified=True)
        rival = User.objects.create_user(username='rival', password='x12345678')
        rival.user_company = other_co
        rival.is_company_admin = True
        rival.save()
        InvoiceHeaderConfig.objects.get(company=self.company)
        self.assertFalse(InvoiceHeaderConfig.objects.filter(company=other_co).exists())

    def test_new_invoice_gets_the_company_defaults(self):
        c = self.client_for(self.admin)
        c.post('/api/invoice-header-config/', {'fields': {
            'payment_status': {'use_default': True, 'default': 'paid'},
            'payment_method': {'visible': False, 'use_default': True, 'default': 'cash'},
            'payment_terms': {'use_default': True, 'default': 30},
            'customer_notes': {'use_default': True, 'default': 'Thanks!'},
        }}, format='json')
        r = c.post('/api/invoice/', {'invoice_type': 'sales', 'date': '2026-08-10'}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        inv = Invoice.objects.get(pk=r.data['id'])
        self.assertEqual((inv.payment_status, inv.payment_method), ('paid', 'cash'))
        self.assertEqual(inv.due_date, datetime.date(2026, 9, 9))
        self.assertEqual(inv.customer_notes, 'Thanks!')

    def test_an_explicit_choice_beats_the_default(self):
        c = self.client_for(self.admin)
        c.post('/api/invoice-header-config/', {'fields': {
            'payment_status': {'use_default': True, 'default': 'paid'}}}, format='json')
        r = c.post('/api/invoice/', {'invoice_type': 'sales', 'payment_status': 'unpaid'}, format='json')
        self.assertEqual(Invoice.objects.get(pk=r.data['id']).payment_status, 'unpaid')

    def test_existing_invoices_are_not_rewritten(self):
        inv = Invoice.objects.create(user=self.admin, payment_status='unpaid',
                                     total_final_amount=Decimal('10'))
        c = self.client_for(self.admin)
        c.post('/api/invoice-header-config/', {'fields': {
            'payment_status': {'use_default': True, 'default': 'paid'}}}, format='json')
        c.post(f'/api/invoice/{inv.id}/update/', {'terms': 'x'}, format='json')
        inv.refresh_from_db()
        self.assertEqual(inv.payment_status, 'unpaid')


class ExistingCompaniesMigrationTests(TestCase):
    """Old companies keep the editor they had; new ones start with everything."""

    def run_migration(self):
        import importlib
        from django.apps import apps
        mod = importlib.import_module(
            'invoice.migrations.0030_hide_header_fields_for_existing_companies')
        mod.hide_for_existing_companies(apps, None)
        return mod

    def test_existing_companies_get_all_six_fields_hidden(self):
        old = UserCompanies.objects.create(company_name='Old Co', is_varified=True)
        self.run_migration()
        fields = hc.normalize(InvoiceHeaderConfig.objects.get(company=old).fields)
        self.assertEqual(set(fields), set(hc.KEYS))
        self.assertTrue(all(not f['visible'] and not f['use_default'] for f in fields.values()))

    def test_it_matches_the_keys_the_app_knows(self):
        mod = self.run_migration()
        self.assertEqual(set(mod.KEYS), set(hc.KEYS))

    def test_a_company_that_already_configured_theirs_is_left_alone(self):
        company = UserCompanies.objects.create(company_name='Configured', is_varified=True)
        InvoiceHeaderConfig.objects.create(company=company, fields=hc.validate(None, {
            'payment_method': {'visible': True, 'use_default': True, 'default': 'upi'}}))
        self.run_migration()
        fields = hc.normalize(InvoiceHeaderConfig.objects.get(company=company).fields)
        self.assertTrue(fields['payment_method']['visible'])
        self.assertEqual(fields['payment_method']['default'], 'upi')

    def test_running_it_twice_changes_nothing(self):
        UserCompanies.objects.create(company_name='Old Co', is_varified=True)
        self.run_migration()
        before = InvoiceHeaderConfig.objects.count()
        self.run_migration()
        self.assertEqual(InvoiceHeaderConfig.objects.count(), before)

    def test_a_company_created_afterwards_sees_every_field(self):
        self.run_migration()
        new_co = UserCompanies.objects.create(company_name='New Co', is_varified=True)
        self.assertFalse(InvoiceHeaderConfig.objects.filter(company=new_co).exists())
        user = User.objects.create_user(username='newbie', password='x12345678')
        user.user_company = new_co
        user.is_company_admin = True
        user.save()
        client = APIClient()
        client.force_authenticate(user=user)
        r = client.get('/api/invoice-header-config/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(all(f['visible'] for f in r.data['fields'].values()))


class LineItemImagesToggleTests(TestCase):
    """The Line item images switch lives on the Invoice Fields screen."""

    def setUp(self):
        cache.clear()
        self.company = UserCompanies.objects.create(company_name='Acme', is_varified=True, state_code=23)
        self.admin = User.objects.create_user(username='boss', password='x12345678')
        self.admin.user_company = self.company
        self.admin.is_company_admin = True
        self.admin.save()
        role, _ = ensure_company_roles(CompanyRole, CompanyPermission, self.company)
        role.users.add(self.admin)
        today = timezone.now().date()
        self.plan_for('pro', today)

    def plan_for(self, code, today):
        CompanySubscription.objects.filter(company=self.company).delete()
        CompanySubscription.objects.create(
            company=self.company, subscription_plan=SubscriptionPlan.objects.get(code=code),
            start_date=today, end_date=today + datetime.timedelta(days=30), status='active')
        cache.clear()

    def api(self):
        c = APIClient()
        c.force_authenticate(user=self.admin)
        return c

    def test_get_reports_availability_and_state(self):
        f = self.api().get('/api/invoice-header-config/').data['features']['line_item_images']
        self.assertEqual(f, {'available': True, 'enabled': False})

    def test_enable_and_disable(self):
        c = self.api()
        r = c.post('/api/invoice-header-config/', {'features': {'line_item_images': True}}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.company.refresh_from_db()
        self.assertTrue(self.company.enable_line_item_images)
        self.assertTrue(r.data['features']['line_item_images']['enabled'])
        r = c.post('/api/invoice-header-config/', {'features': {'line_item_images': False}}, format='json')
        self.company.refresh_from_db()
        self.assertFalse(self.company.enable_line_item_images)

    def test_saving_only_fields_leaves_the_switch_alone(self):
        UserCompanies.objects.filter(pk=self.company.pk).update(enable_line_item_images=True)
        r = self.api().post('/api/invoice-header-config/',
                               {'fields': {'terms': {'visible': False}}}, format='json')
        self.assertEqual(r.status_code, 200, r.data)
        self.company.refresh_from_db()
        self.assertTrue(self.company.enable_line_item_images)

    def test_cannot_enable_without_the_plan_feature(self):
        c = self.api()
        for plan in SubscriptionPlan.objects.exclude(code='pro'):
            self.plan_for(plan.code, timezone.now().date())
            if not c.get('/api/invoice-header-config/').data['features']['line_item_images']['available']:
                break
        else:
            self.skipTest('every seeded plan includes line_item_images')
        r = c.post('/api/invoice-header-config/', {'features': {'line_item_images': True}}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('plan', r.data['error'])
        self.company.refresh_from_db()
        self.assertFalse(self.company.enable_line_item_images)

    def test_an_invalid_fields_payload_does_not_flip_the_switch(self):
        r = self.api().post('/api/invoice-header-config/', {
            'fields': {'payment_status': {'use_default': True, 'default': 'nope'}},
            'features': {'line_item_images': True}}, format='json')
        self.assertEqual(r.status_code, 400)
        self.company.refresh_from_db()
        self.assertFalse(self.company.enable_line_item_images)

    def test_the_company_profile_endpoint_no_longer_changes_it(self):
        from accounts.serializers.UserCompanies import UserCompaniesSerializer
        UserCompanies.objects.filter(pk=self.company.pk).update(enable_line_item_images=True)
        self.company.refresh_from_db()
        # a multipart-style post that simply omits the checkbox, as the form now does
        s = UserCompaniesSerializer(self.company, data={'company_name': 'Acme'}, partial=False)
        s.is_valid()
        self.assertNotIn('enable_line_item_images', s.validated_data)
        self.assertTrue(UserCompaniesSerializer(self.company).data['enable_line_item_images'])
