"""
Regression tests for the multi-tenant subscription/authorization system.

Covers the critical fixes:
- FIX 1: tenant spoofing via X-Company-ID blocked (403)
- FIX 5: trialing subscriptions get features
- FIX 7: m2m permission changes visible on next request (version-bump cache)
- FIX 9: direct deny overrides role grant
- escalation guard: tenant admin can't grant a permission they don't hold
- lockout prevention: last Company Admin can't be removed
- Product Owner APIs blocked for non-staff
"""
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase

from accounts.authz_seed import ensure_company_roles
from accounts.models import (CompanyPermission, CompanyRole, User,
                             UserCompanies)
from companies.models import CompanySubscription, Feature, PlanFeature, SubscriptionPlan


def make_company(name):
    return UserCompanies.objects.create(company_name=name, is_varified=True)


def make_user(username, company, admin=False, superuser=False):
    user = User.objects.create_user(username=username, password='x12345678')
    user.user_company = company
    user.is_company_admin = admin
    if superuser:
        user.is_superuser = True
        user.is_staff = True
    user.save()
    return user


class AuthzTestCase(APITestCase):

    def setUp(self):
        cache.clear()
        self.company_a = make_company('Alpha')
        self.company_b = make_company('Beta')
        self.admin_a = make_user('admin_a', self.company_a, admin=True)
        self.member_a = make_user('member_a', self.company_a)
        self.admin_b = make_user('admin_b', self.company_b, admin=True)
        self.superuser = make_user('root', None, superuser=True)

        # subscription with features for company A
        self.plan = SubscriptionPlan.objects.create(
            name='Pro Test', code='pro_test', monthly_price=1, yearly_price=10)
        feat, _ = Feature.objects.get_or_create(
            code='whatsapp_integration', defaults={'name': 'WhatsApp'})
        PlanFeature.objects.create(subscription_plan=self.plan, feature=feat)
        today = timezone.now().date()
        self.sub = CompanySubscription.objects.create(
            company=self.company_a, subscription_plan=self.plan,
            start_date=today, end_date=today + timedelta(days=30),
            status='trialing')

    def client_for(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    # FIX 1 — tenant spoofing
    def test_x_company_id_spoofing_blocked(self):
        c = self.client_for(self.member_a)
        r = c.get('/api/authz/me/', HTTP_X_COMPANY_ID=str(self.company_b.id))
        self.assertEqual(r.status_code, 403)

    def test_superuser_may_access_other_company(self):
        c = self.client_for(self.superuser)
        r = c.get('/api/authz/me/', HTTP_X_COMPANY_ID=str(self.company_b.id))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['company_id'], self.company_b.id)

    # FIX 5 — trialing subscriptions get features
    def test_trialing_subscription_has_features(self):
        c = self.client_for(self.admin_a)
        r = c.get('/api/authz/me/')
        self.assertEqual(r.status_code, 200)
        self.assertIn('whatsapp_integration', r.data['features'])
        self.assertEqual(r.data['subscription']['status'], 'trialing')

    # FIX 7 — m2m change takes effect on the next request
    def test_role_permission_add_visible_immediately(self):
        c = self.client_for(self.admin_a)
        member_c = self.client_for(self.member_a)
        # bootstrap roles (normally done by signals/seed)
        admin_role, member_role = ensure_company_roles(
            CompanyRole, CompanyPermission, self.company_a)
        admin_role.users.add(self.admin_a)
        member_role.users.add(self.member_a)

        # member lacks role.manage → 403 on authz APIs
        r = member_c.get('/api/authz/roles/')
        self.assertEqual(r.status_code, 403)
        # prime the member's permission cache
        member_c.get('/api/authz/me/')

        # admin grants role.manage to the Member role (m2m change).
        # cache invalidation runs in transaction.on_commit → capture it.
        perm = CompanyPermission.objects.get(code='role.manage', company=None)
        with self.captureOnCommitCallbacks(execute=True):
            member_role.permissions.add(perm)

        # next request must see it (version-bumped cache)
        r = member_c.get('/api/authz/roles/')
        self.assertEqual(r.status_code, 200)

    # FIX 9 — deny wins
    def test_direct_deny_overrides_role_grant(self):
        admin_role, _ = ensure_company_roles(
            CompanyRole, CompanyPermission, self.company_a)
        admin_role.users.add(self.admin_a)
        c = self.client_for(self.admin_a)
        member_role = CompanyRole.objects.get(company=self.company_a, name='Member')
        member_role.users.add(self.member_a)

        perm = CompanyPermission.objects.get(code='invoice.view', company=None)
        r = c.post(f'/api/authz/users/{self.member_a.id}/permissions/',
                   {'permission': perm.id, 'is_granted': False}, format='json')
        self.assertEqual(r.status_code, 201)

        r = c.get(f'/api/authz/users/{self.member_a.id}/effective-permissions/')
        self.assertNotIn('invoice.view', r.data['permissions'])

    # escalation guard
    def test_admin_cannot_grant_permission_they_dont_hold(self):
        admin_role, _ = ensure_company_roles(
            CompanyRole, CompanyPermission, self.company_a)
        admin_role.users.add(self.admin_a)
        # a permission nobody granted to the admin
        secret = CompanyPermission.objects.create(
            name='Secret', code='secret.power', company=None,
            is_system_permission=True)
        c = self.client_for(self.admin_a)
        r = c.post('/api/authz/roles/',
                   {'name': 'Sneaky', 'permissions': [secret.id]}, format='json')
        self.assertEqual(r.status_code, 400)

    # lockout prevention
    def test_cannot_remove_last_company_admin(self):
        admin_role, _ = ensure_company_roles(
            CompanyRole, CompanyPermission, self.company_a)
        admin_role.users.add(self.admin_a)
        c = self.client_for(self.admin_a)
        r = c.delete(f'/api/authz/roles/{admin_role.id}/users/{self.admin_a.id}/')
        self.assertEqual(r.status_code, 400)

    # system role protection
    def test_system_role_not_deletable(self):
        admin_role, _ = ensure_company_roles(
            CompanyRole, CompanyPermission, self.company_a)
        admin_role.users.add(self.admin_a)
        c = self.client_for(self.admin_a)
        r = c.delete(f'/api/authz/roles/{admin_role.id}/')
        self.assertEqual(r.status_code, 403)

    # Product Owner gates
    def test_non_staff_blocked_from_admin_apis(self):
        c = self.client_for(self.admin_a)
        self.assertEqual(c.get('/api/admin/plans/').status_code, 403)

    def test_product_owner_can_assign_subscription(self):
        c = self.client_for(self.superuser)
        r = c.post(f'/api/admin/companies/{self.company_b.id}/subscription/',
                   {'subscription_plan': self.plan.id, 'status': 'active'},
                   format='json')
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.data['plan_code'], 'pro_test')

    # session audit events
    def test_login_logout_and_failed_login_are_audited(self):
        from accounts.models import AuditLog
        c = APIClient()
        r = c.post('/api/login/', {'username': 'admin_a', 'password': 'x12345678'},
                   format='json')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(AuditLog.objects.filter(
            user=self.admin_a, action='LOGIN', resource_type='SESSION').exists())

        c.force_authenticate(user=self.admin_a)
        c.get('/api/log_out/')
        self.assertTrue(AuditLog.objects.filter(
            user=self.admin_a, action='LOGOUT', resource_type='SESSION').exists())

        c2 = APIClient()
        c2.post('/api/login/', {'username': 'admin_a', 'password': 'wrong'},
                format='json')
        self.assertTrue(AuditLog.objects.filter(
            user=self.admin_a, action='LOGIN_FAILED', resource_type='SESSION').exists())

    # user invites
    def test_invite_flow(self):
        from django.test import override_settings
        from accounts.models import UserInvite
        admin_role, _ = ensure_company_roles(
            CompanyRole, CompanyPermission, self.company_a)
        admin_role.users.add(self.admin_a)
        c = self.client_for(self.admin_a)

        with override_settings(
                EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            r = c.post('/api/authz/invites/',
                       {'email': 'hire@example.com'}, format='json')
        self.assertEqual(r.status_code, 201)
        token = UserInvite.objects.get(email='hire@example.com').token

        pub = APIClient()
        r = pub.get(f'/api/invites/{token}/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['valid'])

        r = pub.post(f'/api/invites/{token}/accept/',
                     {'username': 'hire1', 'password': 'strongpass1'},
                     format='json')
        self.assertEqual(r.status_code, 200)
        new_user = User.objects.get(username='hire1')
        self.assertEqual(new_user.user_company_id, self.company_a.id)
        self.assertTrue(new_user.roles.filter(name='Member').exists())

        # token single-use
        r = pub.post(f'/api/invites/{token}/accept/',
                     {'username': 'hire2', 'password': 'strongpass1'},
                     format='json')
        self.assertEqual(r.status_code, 403)

    def test_invite_requires_permission_and_blocks_foreign_members(self):
        from django.test import override_settings
        # member without user.invite → 403
        c = self.client_for(self.member_a)
        r = c.post('/api/authz/invites/', {'email': 'a@b.com'}, format='json')
        self.assertEqual(r.status_code, 403)

        # inviting someone already in another company → 400
        admin_role, _ = ensure_company_roles(
            CompanyRole, CompanyPermission, self.company_a)
        admin_role.users.add(self.admin_a)
        self.admin_b.email = 'takenelsewhere@example.com'
        self.admin_b.save()
        c = self.client_for(self.admin_a)
        with override_settings(
                EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            r = c.post('/api/authz/invites/',
                       {'email': 'takenelsewhere@example.com'}, format='json')
        self.assertEqual(r.status_code, 400)

    # feature gating of existing endpoints
    def test_whatsapp_gated_by_plan_feature(self):
        c = self.client_for(self.member_a)
        # company A's plan includes whatsapp_integration → allowed through the gate
        r = c.get('/api/whatsapp/config/')
        self.assertNotEqual(r.status_code, 403)

        # company B has no subscription → upgrade_required
        c_b = self.client_for(self.admin_b)
        r = c_b.get('/api/whatsapp/config/')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(getattr(r.data.get('detail'), 'code', None), 'upgrade_required')

    def test_invoice_monthly_limit_enforced(self):
        from companies.models import Feature, PlanFeature
        # member needs invoice.create to get past the permission gate
        _, member_role = ensure_company_roles(
            CompanyRole, CompanyPermission, self.company_a)
        member_role.users.add(self.member_a)
        invoicing, _ = Feature.objects.get_or_create(
            code='invoicing', defaults={'name': 'Invoicing'})
        PlanFeature.objects.update_or_create(
            subscription_plan=self.plan, feature=invoicing,
            defaults={'limits': {'invoices_per_month': 0}})
        cache.clear()  # drop cached plan limits/features
        c = self.client_for(self.member_a)
        r = c.post('/api/invoice/', {}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(getattr(r.data.get('detail'), 'code', None), 'upgrade_required')

    # permission gating of invoice/purchase endpoints
    def test_invoice_endpoints_require_permissions(self):
        # user with no roles at all → no invoice permissions
        nobody = make_user('nobody', self.company_a)
        c = self.client_for(nobody)
        self.assertEqual(c.get('/api/invoice/').status_code, 403)
        self.assertEqual(c.get('/api/purchase-summary/').status_code, 403)
        self.assertEqual(c.post('/api/vendors/', {}, format='json').status_code, 403)

        # Member role restores operational access
        _, member_role = ensure_company_roles(
            CompanyRole, CompanyPermission, self.company_a)
        member_role.users.add(nobody)
        with self.captureOnCommitCallbacks(execute=True):
            pass  # role m2m signal invalidation
        cache.clear()
        self.assertEqual(c.get('/api/invoice/').status_code, 200)
        # but invoice.delete is not in the Member set
        self.assertEqual(c.delete('/api/invoice/?id=1').status_code, 403)

    # company-wide reads: members see the whole company's invoices
    def test_member_sees_company_invoices_not_just_own(self):
        from invoice.models import Invoice
        _, member_role = ensure_company_roles(
            CompanyRole, CompanyPermission, self.company_a)
        member_role.users.add(self.member_a)
        # invoice created by the ADMIN (different user, same company)
        Invoice.objects.create(user=self.admin_a, invoice_type='sales')
        # invoice from another company must stay invisible
        Invoice.objects.create(user=self.admin_b, invoice_type='sales')

        c = self.client_for(self.member_a)
        r = c.get('/api/invoice/')
        self.assertEqual(r.status_code, 200)
        results = r.data['results'] if isinstance(r.data, dict) else r.data
        self.assertEqual(len(results), 1)  # company A's invoice only

    # WhatsApp sending modes
    def test_whatsapp_mode_and_shared_account(self):
        from django.test import override_settings
        from companies.models import Feature, PlanFeature
        from whatsapp_integration.models import PlatformWhatsAppAccount
        from accounts.models import UserDirectPermission

        # company A's plan gets the shared-number feature, capped at 0/day
        shared, _ = Feature.objects.get_or_create(
            code='whatsapp_shared_number', defaults={'name': 'Shared WA'})
        PlanFeature.objects.update_or_create(
            subscription_plan=self.plan, feature=shared,
            defaults={'limits': {'sends_per_day': 0}})
        PlatformWhatsAppAccount.objects.create(
            name='Test acct', phone_number_id='123', access_token='tok',
            is_active=True, default_daily_limit=10)
        cache.clear()

        admin_role, _ = ensure_company_roles(
            CompanyRole, CompanyPermission, self.company_a)
        admin_role.users.add(self.admin_a)
        c = self.client_for(self.admin_a)

        # mode endpoint reports both options
        r = c.get('/api/whatsapp/mode/')
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.data['options']['platform']['available'])

        # switch to platform mode (admin has whatsapp.manage)
        r = c.post('/api/whatsapp/mode/', {'mode': 'platform'}, format='json')
        self.assertEqual(r.status_code, 200)

        # member without whatsapp.manage cannot switch modes
        m = self.client_for(self.member_a)
        self.assertEqual(
            m.post('/api/whatsapp/mode/', {'mode': 'own'}, format='json').status_code, 403)

        # share in platform mode hits the 0/day plan cap → upgrade_required
        perm = CompanyPermission.objects.get(code='whatsapp.send', company=None)
        UserDirectPermission.objects.create(
            user=self.member_a, permission=perm, company=self.company_a,
            is_granted=True, granted_by=self.admin_a)
        from invoice_api.middleware import bump_perm_version
        bump_perm_version(self.company_a.id)
        cache.clear()
        from companies.models import Customers
        from invoice.models import Invoice
        cust = Customers.objects.create(
            user=self.admin_a, name='Cust', phone_number='9876543210')
        inv = Invoice.objects.create(
            user=self.admin_a, invoice_type='sales', receiver=cust)
        r = m.post('/api/share_by_whatsapp/', {'invoice': inv.id}, format='json')
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.data.get('code'), 'upgrade_required')

    def test_platform_whatsapp_account_admin_api(self):
        c = self.client_for(self.superuser)
        r = c.get('/api/admin/whatsapp-account/')
        self.assertEqual(r.status_code, 200)
        r = c.put('/api/admin/whatsapp-account/',
                  {'default_daily_limit': 42, 'access_token': 'newtok123'},
                  format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['default_daily_limit'], 42)
        self.assertTrue(r.data['has_access_token'])
        # tenant admin blocked
        t = self.client_for(self.admin_a)
        self.assertEqual(t.get('/api/admin/whatsapp-account/').status_code, 403)

    # tenant isolation of the authz APIs themselves
    def test_roles_scoped_to_own_company(self):
        for company, admin in ((self.company_a, self.admin_a),
                               (self.company_b, self.admin_b)):
            role, _ = ensure_company_roles(CompanyRole, CompanyPermission, company)
            role.users.add(admin)
        c = self.client_for(self.admin_a)
        r = c.get('/api/authz/roles/')
        data = r.data if isinstance(r.data, list) else r.data.get('results', r.data)
        for role in data:
            self.assertNotIn('Beta', str(role))
