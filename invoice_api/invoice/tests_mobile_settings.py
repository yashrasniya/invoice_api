"""Contract tests for the Phase 5 screens: team & invites, WhatsApp mode, templates,
numbering, billing. Pins the request/response shapes MobileApp/services/* rely on."""
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core import mail
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from accounts.authz_seed import ensure_company_roles
from accounts.models import CompanyPermission, CompanyRole, UserCompanies, UserInvite
from invoice.tests_numbering import give_plan
from yaml_manager.models import Yaml

User = get_user_model()


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class MobileSettingsContractTest(TestCase):
    def setUp(self):
        cache.clear()   # plan/feature lookups are cached per company id, and ids repeat across tests
        self.company = UserCompanies.objects.create(company_name='Acme', is_varified=True)
        self.admin = User.objects.create_user(username='boss', email='boss@e.com', password='x')
        self.admin.user_company = self.company
        self.admin.is_company_admin = True
        self.admin.save()
        self.member = User.objects.create_user(username='emp', email='emp@e.com', password='x')
        self.member.user_company = self.company
        self.member.save()
        give_plan(self.company, ['invoicing', 'template_designer', 'whatsapp_integration', 'whatsapp_shared_number'],
                  limits={'invoicing': {'users': 10}})
        self.admin_role, self.member_role = ensure_company_roles(CompanyRole, CompanyPermission, self.company)
        self.admin_role.users.add(self.admin)
        self.member_role.users.add(self.member)
        self.c = APIClient()
        self.c.force_authenticate(user=self.admin)

    # ── team ────────────────────────────────────────────────────────────────
    def test_members_and_roles_shape(self):
        members = self.c.get('/api/authz/users/').data
        self.assertEqual({m['username'] for m in members}, {'boss', 'emp'})
        self.assertTrue({'id', 'username', 'first_name', 'last_name', 'email'} <= set(members[0]))
        roles = self.c.get('/api/authz/roles/').data
        role = next(r for r in roles if r['name'] == 'Member')
        for k in ('id', 'name', 'description', 'is_system_role', 'permission_codes', 'user_names'):
            self.assertIn(k, role)
        self.assertEqual(role['user_names'], [{'id': self.member.id, 'username': 'emp'}])

    def test_assign_and_unassign_role_and_last_admin_guard(self):
        self.assertEqual(self.c.post(f'/api/authz/roles/{self.admin_role.id}/users/',
                                     {'user_id': self.member.id}, format='json').status_code, 200)
        self.assertTrue(self.admin_role.users.filter(pk=self.member.pk).exists())
        self.assertEqual(self.c.delete(f'/api/authz/roles/{self.admin_role.id}/users/{self.member.id}/').status_code, 200)
        # removing the only remaining admin must be refused
        res = self.c.delete(f'/api/authz/roles/{self.admin_role.id}/users/{self.admin.id}/')
        self.assertEqual(res.status_code, 400)

    def test_invite_lifecycle(self):
        res = self.c.post('/api/authz/invites/', {'email': 'new@e.com', 'role': self.member_role.id}, format='json')
        self.assertEqual(res.status_code, 201, res.content)
        for k in ('id', 'email', 'role_name', 'status', 'expires_at', 'invite_link', 'mail_sent'):
            self.assertIn(k, res.data)
        self.assertTrue(res.data['mail_sent'])
        self.assertEqual(len(mail.outbox), 1)
        inv_id = res.data['id']

        listed = self.c.get('/api/authz/invites/').data
        self.assertEqual([i['email'] for i in listed], ['new@e.com'])
        self.assertEqual(self.c.post(f'/api/authz/invites/{inv_id}/resend/').data, {'mail_sent': True})

        dup = self.c.post('/api/authz/invites/', {'email': 'new@e.com'}, format='json')
        self.assertEqual(dup.status_code, 400)

        self.assertEqual(self.c.delete(f'/api/authz/invites/{inv_id}/').status_code, 204)
        self.assertEqual(UserInvite.objects.get(pk=inv_id).status, 'revoked')

    def test_member_cannot_manage_team(self):
        m = APIClient()
        m.force_authenticate(user=self.member)
        for url in ('/api/authz/users/', '/api/authz/roles/', '/api/authz/audit-log/', '/api/authz/invites/'):
            self.assertEqual(m.get(url).status_code, 403, url)

    def test_audit_log_shape(self):
        self.c.post('/api/authz/invites/', {'email': 'a@e.com'}, format='json')
        rows = self.c.get('/api/authz/audit-log/').data
        self.assertTrue(rows)
        self.assertTrue({'id', 'user_name', 'action', 'resource_type', 'timestamp'} <= set(rows[0]))

    # ── WhatsApp ────────────────────────────────────────────────────────────
    def test_whatsapp_mode_read_and_update(self):
        d = self.c.get('/api/whatsapp/mode/').data
        self.assertIn(d['mode'], ('platform', 'own'))
        for k in ('platform', 'own'):
            self.assertTrue({'available', 'in_plan', 'configured', 'sends_per_day'} <= set(d['options'][k]))
        self.assertIn('default_invoice_template', d)

        t = Yaml.objects.create(template_name='Mine', company=self.company, user=self.admin)
        res = self.c.post('/api/whatsapp/mode/', {'default_invoice_template': t.id}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(self.c.get('/api/whatsapp/mode/').data['default_invoice_template']['id'], t.id)
        res = self.c.post('/api/whatsapp/mode/', {'default_invoice_template': None}, format='json')
        self.assertIsNone(res.data['default_invoice_template'])

    def test_whatsapp_unconfigured_state_is_404_not_a_crash(self):
        res = self.c.get('/api/whatsapp/config/')
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.data['status'], 'not_configured')   # the app maps this to "not connected"
        self.assertEqual(list(self.c.get('/api/whatsapp/template/').data), [])

    # ── templates & numbering ───────────────────────────────────────────────
    def test_templates_list_gallery_default_and_clone(self):
        mine = Yaml.objects.create(template_name='One', company=self.company, user=self.admin, is_default=True)
        other = Yaml.objects.create(template_name='Two', company=self.company, user=self.admin)
        listed = self.c.get('/api/yaml/list/', {'only_my': 1}).data
        listed = listed['results'] if isinstance(listed, dict) else listed
        self.assertEqual({t['template_name'] for t in listed}, {'One', 'Two'})
        self.assertTrue({'id', 'template_name', 'pdf_template', 'is_default', 'is_html'} <= set(listed[0]))

        self.assertEqual(self.c.post(f'/api/yaml/{other.id}/set-default/').status_code, 200)
        mine.refresh_from_db(); other.refresh_from_db()
        self.assertFalse(mine.is_default)
        self.assertTrue(other.is_default)

        g = Yaml.objects.create(template_name='Gallery one', is_global=True, is_published=True,
                                global_category='Retail', user=self.admin)
        gallery = self.c.get('/api/yaml/gallery/').data
        gallery = gallery['results'] if isinstance(gallery, dict) else gallery
        self.assertTrue({'id', 'template_name', 'global_category', 'preview_url', 'pdf_template'} <= set(gallery[0]))
        self.assertEqual(self.c.post(f'/api/yaml/gallery/{g.id}/clone/').status_code, 201)
        self.assertEqual(Yaml.objects.filter(company=self.company, template_name='Gallery one', is_global=False).count(), 1)

    def test_numbering_get_preview_and_save(self):
        d = self.c.get('/api/invoice-numbering/').data
        for k in ('enabled', 'template', 'reset_period', 'next_number', 'tokens', 'reset_options', 'preview'):
            self.assertIn(k, d)
        bad = self.c.get('/api/invoice-numbering/', {'template': 'INV-{NOPE}', 'reset_period': 'never', 'next_number': 1})
        self.assertEqual(bad.status_code, 200)             # half-typed templates are not client errors
        self.assertFalse(bad.data['valid'])
        good = self.c.get('/api/invoice-numbering/', {'template': 'INV-{SEQ:4}', 'reset_period': 'never', 'next_number': 7}).data
        self.assertEqual(good['preview'], 'INV-0007')

        saved = self.c.post('/api/invoice-numbering/', {'enabled': True, 'template': 'INV-{SEQ:4}',
                                                        'reset_period': 'never', 'next_number': 7}, format='json')
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertTrue(saved.data['enabled'])
        m = APIClient(); m.force_authenticate(user=self.member)
        self.assertEqual(m.post('/api/invoice-numbering/', {'template': 'X{SEQ}'}, format='json').status_code, 403)

    # ── billing (read-only in the app) ─────────────────────────────────────
    def test_billing_status_plans_payments_shape(self):
        s = self.c.get('/api/billing/subscription/').data
        self.assertTrue({'entitlement', 'billing_subscription', 'scheduled_change'} <= set(s))
        self.assertTrue({'plan_name', 'status', 'end_date', 'auto_renew', 'is_working'} <= set(s['entitlement']))
        plans = self.c.get('/api/billing/plans/').data['plans']
        self.assertTrue({'id', 'name', 'monthly_price', 'yearly_price', 'features', 'is_current'} <= set(plans[0]))
        self.assertTrue(any(p['is_current'] for p in plans))
        pays = self.c.get('/api/billing/payments/').data
        self.assertEqual(pays if isinstance(pays, list) else pays['results'], [])
