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
