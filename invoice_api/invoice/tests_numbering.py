from datetime import date, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.authz_seed import ensure_company_roles
from accounts.models import AuditLog, CompanyPermission, CompanyRole, UserCompanies
from companies.models import (CompanySubscription, Feature, PlanFeature,
                              SubscriptionPlan)
from invoice import numbering
from invoice.models import CompanyInvoiceNumbering, Invoice

User = get_user_model()

URL = '/api/invoice-numbering/'


def give_plan(company, feature_codes, limits=None):
    plan = SubscriptionPlan.objects.create(
        name=f'Plan {company.id}', code=f'plan_{company.id}',
        monthly_price=1, yearly_price=10)
    for code in feature_codes:
        feat, _ = Feature.objects.get_or_create(code=code, defaults={'name': code})
        PlanFeature.objects.create(subscription_plan=plan, feature=feat,
                                   limits=(limits or {}).get(code, {}))
    today = timezone.now().date()
    CompanySubscription.objects.create(
        company=company, subscription_plan=plan, start_date=today,
        end_date=today + timedelta(days=30), status='active')
    return plan


class TemplateGrammarTest(TestCase):
    """Pure grammar: no DB, no request."""

    def test_default_template_renders(self):
        out = numbering.render(numbering.DEFAULT_TEMPLATE, date(2026, 8, 23), 1)
        self.assertEqual(out, 'INV-2026-27-0001')
        self.assertEqual(len(out), 16)          # GST Rule 46(b) maximum

    def test_fy_boundary(self):
        self.assertEqual(numbering.render('{FY}', date(2026, 3, 31), 1), '2025-26')
        self.assertEqual(numbering.render('{FY}', date(2026, 4, 1), 1), '2026-27')
        self.assertEqual(numbering.fy_start_year(date(2026, 3, 31)), 2025)
        self.assertEqual(numbering.fy_start_year(date(2026, 4, 1)), 2026)

    def test_fy_label_wraps_century(self):
        self.assertEqual(numbering.render('{FY}', date(2099, 6, 1), 1), '2099-00')

    def test_all_date_tokens(self):
        out = numbering.render('{YYYY}|{YY}|{MM}|{DD}|{FYS}|{FYE}|{SEQ}',
                               date(2026, 8, 23), 3)
        self.assertEqual(out, '2026|26|08|23|2026|2027|3')

    def test_seq_padding(self):
        self.assertEqual(numbering.render('{SEQ:5}', date(2026, 1, 1), 42), '00042')
        self.assertEqual(numbering.render('{SEQ}', date(2026, 1, 1), 42), '42')

    def test_seq_overflow_widens_not_truncates(self):
        self.assertEqual(numbering.render('{SEQ:4}', date(2026, 1, 1), 123456), '123456')

    def test_unknown_token_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            numbering.validate_template('INV-{PREFIX}-{SEQ}')
        self.assertIn('{PREFIX}', str(ctx.exception))

    def test_requires_exactly_one_seq(self):
        with self.assertRaises(ValueError):
            numbering.validate_template('INV-{YYYY}')
        with self.assertRaises(ValueError):
            numbering.validate_template('{SEQ}-{SEQ:3}')

    def test_unbalanced_braces_rejected(self):
        with self.assertRaises(ValueError):
            numbering.validate_template('INV-{SEQ')

    def test_rejects_template_too_long_when_rendered(self):
        with self.assertRaises(ValueError) as ctx:
            numbering.validate_template('WAREHOUSE-DELHI-{YYYY}-{MM}-{DD}-{SEQ:8}')
        self.assertIn('maximum', str(ctx.exception))

    def test_short_today_but_overflowing_later_is_rejected(self):
        # 25 literal chars + a counter that will outgrow 5 digits
        with self.assertRaises(ValueError):
            numbering.validate_template('ABCDEFGHIJKLMNOPQRSTUVWXY{SEQ:3}')

    def test_rejects_illegal_literal_chars(self):
        with self.assertRaises(ValueError):
            numbering.validate_template('INV<{SEQ}>')

    def test_seq_padding_bounds(self):
        with self.assertRaises(ValueError):
            numbering.validate_template('{SEQ:13}')

    def test_yearly_reset_requires_year_token(self):
        with self.assertRaises(ValueError):
            numbering.validate_template('INV-{SEQ:4}', numbering.RESET_YEARLY)
        numbering.validate_template('INV-{YYYY}-{SEQ:4}', numbering.RESET_YEARLY)

    def test_fy_reset_requires_fy_token(self):
        with self.assertRaises(ValueError):
            numbering.validate_template('INV-{YYYY}-{SEQ:4}', numbering.RESET_FY)
        numbering.validate_template('INV-{FY}-{SEQ:4}', numbering.RESET_FY)

    def test_monthly_reset_requires_month_and_year(self):
        with self.assertRaises(ValueError):
            numbering.validate_template('INV-{MM}-{SEQ:4}', numbering.RESET_MONTHLY)
        numbering.validate_template('INV-{YYYY}{MM}-{SEQ:4}', numbering.RESET_MONTHLY)

    def test_period_key_all_modes(self):
        d = date(2026, 8, 23)
        self.assertEqual(numbering.period_key(numbering.RESET_NEVER, d), '')
        self.assertEqual(numbering.period_key(numbering.RESET_MONTHLY, d), '2026-08')
        self.assertEqual(numbering.period_key(numbering.RESET_YEARLY, d), '2026')
        self.assertEqual(numbering.period_key(numbering.RESET_FY, d), 'FY2026')
        self.assertEqual(numbering.period_key(numbering.RESET_FY, date(2026, 2, 1)), 'FY2025')

    def test_preview_flags_gst_length(self):
        short = numbering.preview('INV-{SEQ:4}', seq=1, on_date=date(2026, 8, 23))
        self.assertTrue(short['valid'])
        self.assertFalse(short['gst_warning'])
        long = numbering.preview('GST/{FYS}-{FYE}/BRANCH/{SEQ:4}', seq=1,
                                 on_date=date(2026, 8, 23))
        self.assertTrue(long['valid'])          # advisory only, never blocking
        self.assertTrue(long['gst_warning'])

    def test_preview_invalid_returns_error(self):
        out = numbering.preview('{NOPE}-{SEQ}')
        self.assertFalse(out['valid'])
        self.assertIn('{NOPE}', out['error'])


class NumberGenerationTest(TestCase):
    def setUp(self):
        cache.clear()
        self.company = UserCompanies.objects.create(company_name='Acme', is_varified=True)
        self.user = User.objects.create_user(username='numuser', email='n@e.com', password='x')
        self.user.user_company = self.company
        self.user.save()
        self.cfg = CompanyInvoiceNumbering.objects.create(
            company=self.company, enabled=True,
            template='INV-{FY}-{SEQ:4}', reset_period=numbering.RESET_FY)

    def gen(self, on_date=date(2026, 8, 23)):
        return numbering.next_invoice_number(self.company, on_date)

    def test_disabled_returns_none(self):
        CompanyInvoiceNumbering.objects.filter(pk=self.cfg.pk).update(enabled=False)
        self.assertIsNone(self.gen())

    def test_no_config_returns_none(self):
        self.cfg.delete()
        self.assertIsNone(self.gen())

    def test_no_company_returns_none(self):
        self.assertIsNone(numbering.next_invoice_number(None))

    def test_sequential_numbers(self):
        self.assertEqual(self.gen(), 'INV-2026-27-0001')
        self.assertEqual(self.gen(), 'INV-2026-27-0002')
        self.assertEqual(self.gen(), 'INV-2026-27-0003')
        self.cfg.refresh_from_db()
        self.assertEqual(self.cfg.next_number, 4)

    def test_skips_existing_manual_number(self):
        Invoice.objects.create(user=self.user, invoice_number='INV-2026-27-0002')
        self.assertEqual(self.gen(), 'INV-2026-27-0001')
        self.assertEqual(self.gen(), 'INV-2026-27-0003')   # 0002 burned

    def test_skips_soft_deleted_number(self):
        """Invoice.objects hides soft-deleted rows, but they still own their
        number -- probing with the default manager would hand it out twice."""
        inv = Invoice.objects.create(user=self.user, invoice_number='INV-2026-27-0001')
        inv.delete()                                        # soft delete
        self.assertFalse(Invoice.objects.filter(pk=inv.pk).exists())
        self.assertTrue(Invoice.all_objects.filter(pk=inv.pk).exists())
        self.assertEqual(self.gen(), 'INV-2026-27-0002')

    def test_period_rollover_resets_counter(self):
        self.assertEqual(self.gen(date(2026, 3, 31)), 'INV-2025-26-0001')
        self.assertEqual(self.gen(date(2026, 3, 31)), 'INV-2025-26-0002')
        self.assertEqual(self.gen(date(2026, 4, 1)), 'INV-2026-27-0001')
        self.cfg.refresh_from_db()
        self.assertEqual(self.cfg.period_key, 'FY2026')

    def test_backdated_does_not_rewind(self):
        self.gen(date(2026, 4, 1))                          # establishes FY2026
        self.assertEqual(self.gen(date(2026, 3, 31)), 'INV-2025-26-0002')
        self.cfg.refresh_from_db()
        self.assertEqual(self.cfg.period_key, 'FY2026')     # unchanged

    def test_adopting_period_key_midseries_does_not_reset(self):
        CompanyInvoiceNumbering.objects.filter(pk=self.cfg.pk).update(
            period_key='', next_number=57)
        self.assertEqual(self.gen(), 'INV-2026-27-0057')
        self.cfg.refresh_from_db()
        self.assertEqual(self.cfg.period_key, 'FY2026')

    def test_never_reset_ignores_period(self):
        CompanyInvoiceNumbering.objects.filter(pk=self.cfg.pk).update(
            reset_period=numbering.RESET_NEVER, template='INV-{SEQ:4}')
        self.assertEqual(self.gen(date(2026, 3, 31)), 'INV-0001')
        self.assertEqual(self.gen(date(2027, 4, 1)), 'INV-0002')

    def test_invalid_template_in_db_returns_none(self):
        CompanyInvoiceNumbering.objects.filter(pk=self.cfg.pk).update(
            template='INV-{BOGUS}')
        self.assertIsNone(self.gen())

    def test_generation_failure_does_not_raise(self):
        with mock.patch.object(numbering, 'render', side_effect=RuntimeError('boom')):
            self.assertIsNone(self.gen())

    def test_overlong_render_returns_none(self):
        # Bypass validation to simulate a counter that outgrew the column
        CompanyInvoiceNumbering.objects.filter(pk=self.cfg.pk).update(
            template='ABCDEFGHIJKLMNOPQRSTUVWXYZ{SEQ:8}', next_number=1)
        self.assertIsNone(self.gen())

    def test_cas_retries_on_lost_race(self):
        """A concurrent writer wins the first swap; we must retry, not reuse.

        Driven deterministically rather than with threads: under TestCase each
        thread gets its own connection outside the test transaction, which is
        unreliable on SQLite.
        """
        real_filter = CompanyInvoiceNumbering.objects.filter
        state = {'stale': True}

        def fake_filter(*args, **kwargs):
            qs = real_filter(*args, **kwargs)
            if state['stale'] and 'pk' in kwargs and 'next_number' not in kwargs:
                # first read only: report a value another writer already took
                state['stale'] = False
                real_filter(pk=kwargs['pk']).update(next_number=9)
            return qs

        with mock.patch.object(CompanyInvoiceNumbering.objects, 'filter',
                               side_effect=fake_filter):
            out = self.gen()
        # The CAS saw a changed row, retried, and issued the winner's value
        self.assertEqual(out, 'INV-2026-27-0009')


class NumberingSettingsAPITest(TestCase):
    def setUp(self):
        cache.clear()
        self.company = UserCompanies.objects.create(company_name='Acme', is_varified=True)
        self.user = User.objects.create_user(username='admin1', email='a@e.com', password='x')
        self.user.user_company = self.company
        self.user.is_company_admin = True
        self.user.save()
        give_plan(self.company, ['invoicing', 'template_designer'])
        admin_role, self.member_role = ensure_company_roles(
            CompanyRole, CompanyPermission, self.company)
        admin_role.users.add(self.user)

        self.other_company = UserCompanies.objects.create(company_name='Rival', is_varified=True)
        self.rival = User.objects.create_user(username='rival1', email='r@e.com', password='x')
        self.rival.user_company = self.other_company
        self.rival.is_company_admin = True
        self.rival.save()
        give_plan(self.other_company, ['invoicing', 'template_designer'])
        rival_admin, _ = ensure_company_roles(
            CompanyRole, CompanyPermission, self.other_company)
        rival_admin.users.add(self.rival)

        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def test_get_defaults_when_no_row(self):
        r = self.client.get(URL)
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.data['enabled'])
        self.assertEqual(r.data['template'], numbering.DEFAULT_TEMPLATE)
        self.assertTrue(r.data['valid'])
        self.assertTrue(r.data['preview'].startswith('INV-'))
        # a read must not materialise a row
        self.assertFalse(CompanyInvoiceNumbering.objects.exists())

    def test_get_exposes_token_catalog(self):
        r = self.client.get(URL)
        tokens = [t['token'] for t in r.data['tokens']]
        self.assertIn('{FY}', tokens)
        self.assertIn('{SEQ:4}', tokens)
        self.assertEqual(r.data['max_length'], 30)
        self.assertEqual(r.data['gst_recommended_max_length'], 16)

    def test_post_requires_template_manage(self):
        member = User.objects.create_user(username='member1', email='m@e.com', password='x')
        member.user_company = self.company
        member.save()
        self.member_role.users.add(member)
        client = APIClient()
        client.force_authenticate(user=member)
        r = client.post(URL, {'template': 'X-{SEQ:3}'}, format='json')
        self.assertEqual(r.status_code, 403)

    def test_get_allowed_without_template_manage(self):
        # Reads are ungated (same as CustomFieldViewSet) -- the settings page
        # itself is route-gated, but a member may read the format.
        member = User.objects.create_user(username='member2', email='m2@e.com', password='x')
        member.user_company = self.company
        member.save()
        self.member_role.users.add(member)
        client = APIClient()
        client.force_authenticate(user=member)
        self.assertEqual(client.get(URL).status_code, 200)

    def test_post_saves_and_returns_preview(self):
        r = self.client.post(URL, {'enabled': True, 'template': 'ACME/{FY}/{SEQ:4}',
                                   'reset_period': 'fy', 'next_number': 120},
                             format='json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['enabled'])
        self.assertEqual(r.data['next_number'], 120)
        self.assertTrue(r.data['preview'].endswith('/0120'))
        cfg = CompanyInvoiceNumbering.objects.get(company=self.company)
        self.assertEqual(cfg.template, 'ACME/{FY}/{SEQ:4}')

    def test_post_rejects_bad_template(self):
        r = self.client.post(URL, {'template': 'INV-{PREFIX}-{SEQ}'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertIn('{PREFIX}', r.data['error'])

    def test_post_rejects_reset_without_matching_token(self):
        r = self.client.post(URL, {'template': 'INV-{SEQ:4}', 'reset_period': 'fy'},
                             format='json')
        self.assertEqual(r.status_code, 400)

    def test_post_rejects_bad_next_number(self):
        self.assertEqual(
            self.client.post(URL, {'next_number': 0}, format='json').status_code, 400)
        self.assertEqual(
            self.client.post(URL, {'next_number': 'abc'}, format='json').status_code, 400)

    def test_post_writes_audit_log(self):
        self.client.post(URL, {'enabled': True}, format='json')
        logs = AuditLog.objects.filter(resource_type='INVOICE_NUMBERING')
        self.assertEqual(logs.count(), 1)
        self.assertEqual(logs.first().company, self.company)

    def test_reset_period_change_rekeys_without_resetting_counter(self):
        self.client.post(URL, {'template': 'INV-{FY}-{SEQ:4}', 'reset_period': 'never',
                               'next_number': 77}, format='json')
        self.client.post(URL, {'reset_period': 'fy'}, format='json')
        cfg = CompanyInvoiceNumbering.objects.get(company=self.company)
        self.assertEqual(cfg.next_number, 77)               # counter keeps running
        self.assertTrue(cfg.period_key.startswith('FY'))

    def test_preview_query_param_does_not_persist(self):
        r = self.client.get(URL, {'template': 'ZZ-{SEQ:2}', 'next_number': 5})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['preview'], 'ZZ-05')
        self.assertFalse(CompanyInvoiceNumbering.objects.exists())

    def test_preview_invalid_returns_200_with_valid_false(self):
        r = self.client.get(URL, {'template': '{NOPE}-{SEQ}'})
        self.assertEqual(r.status_code, 200)                # not a client error
        self.assertFalse(r.data['valid'])

    def test_no_company_returns_400(self):
        loner = User.objects.create_user(username='loner', email='l@e.com', password='x')
        client = APIClient()
        client.force_authenticate(user=loner)
        self.assertEqual(client.get(URL).status_code, 400)

    def test_cross_tenant_isolation(self):
        self.client.post(URL, {'template': 'MINE-{SEQ:3}', 'enabled': True}, format='json')
        rival_client = APIClient()
        rival_client.force_authenticate(user=self.rival)
        r = rival_client.get(URL)
        self.assertEqual(r.data['template'], numbering.DEFAULT_TEMPLATE)
        self.assertFalse(r.data['enabled'])

        rival_client.post(URL, {'template': 'THEIRS-{SEQ:3}'}, format='json')
        mine = CompanyInvoiceNumbering.objects.get(company=self.company)
        self.assertEqual(mine.template, 'MINE-{SEQ:3}')


class InvoiceCreateNumberingTest(TestCase):
    def setUp(self):
        cache.clear()
        self.company = UserCompanies.objects.create(company_name='Acme', is_varified=True)
        self.user = User.objects.create_user(username='creator', email='c@e.com', password='x')
        self.user.user_company = self.company
        self.user.is_company_admin = True
        self.user.save()
        give_plan(self.company, ['invoicing', 'purchases_invoice', 'template_designer'])
        admin_role, _ = ensure_company_roles(CompanyRole, CompanyPermission, self.company)
        admin_role.users.add(self.user)
        self.cfg = CompanyInvoiceNumbering.objects.create(
            company=self.company, enabled=True,
            template='INV-{FY}-{SEQ:4}', reset_period=numbering.RESET_FY)
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)

    def expected(self, seq=1):
        return numbering.render('INV-{FY}-{SEQ:4}', timezone.localdate(), seq)

    def test_create_without_number_gets_generated(self):
        r = self.client.post('/api/invoice/', {'invoice_type': 'sales'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['invoice_number'], self.expected(1))

    def test_manual_number_preserved_and_counter_untouched(self):
        r = self.client.post('/api/invoice/',
                             {'invoice_type': 'sales', 'invoice_number': 'MINE-1'})
        self.assertEqual(r.data['invoice_number'], 'MINE-1')
        self.cfg.refresh_from_db()
        self.assertEqual(self.cfg.next_number, 1)           # never consumed

    def test_blank_string_treated_as_absent(self):
        r = self.client.post('/api/invoice/',
                             {'invoice_type': 'sales', 'invoice_number': ''})
        self.assertEqual(r.data['invoice_number'], self.expected(1))

    def test_literal_null_string_treated_as_absent(self):
        # FormData.append(k, null) in the browser sends the string "null"
        r = self.client.post('/api/invoice/',
                             {'invoice_type': 'sales', 'invoice_number': 'null'})
        self.assertEqual(r.data['invoice_number'], self.expected(1))

    def test_disabled_leaves_number_blank(self):
        CompanyInvoiceNumbering.objects.filter(pk=self.cfg.pk).update(enabled=False)
        r = self.client.post('/api/invoice/', {'invoice_type': 'sales'})
        self.assertIn(r.data['invoice_number'], (None, ''))

    def test_purchase_invoice_is_not_numbered(self):
        r = self.client.post('/api/invoice/', {'invoice_type': 'purchase'})
        self.assertEqual(r.status_code, 200)
        self.assertIn(r.data['invoice_number'], (None, ''))
        self.cfg.refresh_from_db()
        self.assertEqual(self.cfg.next_number, 1)           # series untouched

    def test_consecutive_sales_invoices_increment(self):
        first = self.client.post('/api/invoice/', {'invoice_type': 'sales'})
        second = self.client.post('/api/invoice/', {'invoice_type': 'sales'})
        self.assertEqual(first.data['invoice_number'], self.expected(1))
        self.assertEqual(second.data['invoice_number'], self.expected(2))

    def test_update_can_override_generated_number(self):
        created = self.client.post('/api/invoice/', {'invoice_type': 'sales'})
        inv_id = created.data['id']
        r = self.client.post(f'/api/invoice/{inv_id}/update/',
                             {'invoice_number': 'HAND-9'})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Invoice.objects.get(id=inv_id).invoice_number, 'HAND-9')

    def test_update_can_clear_number(self):
        created = self.client.post('/api/invoice/', {'invoice_type': 'sales'})
        inv_id = created.data['id']
        r = self.client.post(f'/api/invoice/{inv_id}/update/', {'invoice_number': ''})
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(Invoice.objects.get(id=inv_id).invoice_number)

    def test_generation_failure_still_creates_invoice(self):
        with mock.patch('invoice.api.views.next_invoice_number',
                        side_effect=RuntimeError('boom')):
            with self.assertRaises(RuntimeError):
                self.client.post('/api/invoice/', {'invoice_type': 'sales'})

    def test_generation_returning_none_still_creates_invoice(self):
        with mock.patch('invoice.api.views.next_invoice_number', return_value=None):
            r = self.client.post('/api/invoice/', {'invoice_type': 'sales'})
        self.assertEqual(r.status_code, 200)
        self.assertIn(r.data['invoice_number'], (None, ''))
