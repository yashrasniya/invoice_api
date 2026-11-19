"""Platform Admin (product owner) APIs: overview, company list filters and
pagination, subscription audit, feature delete guard, audit log filters.

    python manage.py test companies.tests_platform_admin
"""
from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import AuditLog, User, UserCompanies
from companies.models import (CompanySubscription, Feature, PlanFeature,
                              SubscriptionPlan)


class PlatformAdminTestBase(TestCase):
    def setUp(self):
        CompanySubscription.objects.all().delete()
        self.free, _ = SubscriptionPlan.objects.get_or_create(
            code='free_t', defaults={'name': 'Free T'})
        self.pro, _ = SubscriptionPlan.objects.get_or_create(
            code='pro_t', defaults={'name': 'Pro T', 'monthly_price': 499,
                                    'yearly_price': 4990})
        self.today = timezone.localdate()

        self.acme = UserCompanies.objects.create(company_name='Acme Traders',
                                                 company_email_id='a@acme.test')
        self.beta = UserCompanies.objects.create(company_name='Beta Foods')
        self.gamma = UserCompanies.objects.create(company_name='Gamma Ltd')
        CompanySubscription.objects.all().delete()

        CompanySubscription.objects.create(
            company=self.acme, subscription_plan=self.pro, status='active',
            start_date=self.today - timedelta(days=10),
            end_date=self.today + timedelta(days=5))
        CompanySubscription.objects.create(
            company=self.beta, subscription_plan=self.pro, status='trialing',
            start_date=self.today, end_date=self.today + timedelta(days=3))
        # gamma: no plan

        self.owner = User.objects.create_user(username='owner', password='x12345678')
        self.owner.is_superuser = True
        self.owner.save()
        # the custom create_user ignores extra fields, so set the company after
        self.tenant = User.objects.create_user(username='tenant', password='x12345678')
        self.tenant.user_company = self.acme
        self.tenant.save()

        self.client = APIClient()
        self.client.force_authenticate(self.owner)


class AccessTests(PlatformAdminTestBase):
    def test_new_and_changed_endpoints_require_product_owner(self):
        c = APIClient()
        c.force_authenticate(self.tenant)
        for path in ('/api/admin/overview/', '/api/admin/companies/',
                     '/api/admin/audit-log/', '/api/admin/audit-log/facets/',
                     '/api/admin/features/', '/api/admin/billing/webhook-events/'):
            self.assertEqual(c.get(path).status_code, 403, path)


class OverviewTests(PlatformAdminTestBase):
    def test_counts(self):
        r = self.client.get('/api/admin/overview/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['companies'], 3)
        self.assertEqual(r.data['subscriptions']['active'], 1)
        self.assertEqual(r.data['subscriptions']['trialing'], 1)
        self.assertEqual(r.data['subscriptions']['none'], 1)
        self.assertEqual(r.data['trials_ending_7d'], 1)
        self.assertEqual(r.data['subs_ending_30d'], 1)
        self.assertEqual(r.data['mrr_estimate'], '499.00')
        pro = next(p for p in r.data['plans'] if p['code'] == 'pro_t')
        self.assertEqual(pro['subscribers'], 2)
        self.assertIn('billing', r.data)


class CompanyListTests(PlatformAdminTestBase):
    def ids(self, query=''):
        r = self.client.get(f'/api/admin/companies/{query}')
        self.assertEqual(r.status_code, 200)
        return {c['id'] for c in r.data['results']}

    def test_paginated_shape(self):
        r = self.client.get('/api/admin/companies/?page_size=2')
        self.assertEqual(r.data['count'], 3)
        self.assertEqual(len(r.data['results']), 2)
        self.assertIsNotNone(r.data['next'])

    def test_filters(self):
        self.assertEqual(self.ids('?search=acme'), {self.acme.id})
        self.assertEqual(self.ids('?search=a@acme'), {self.acme.id})
        self.assertEqual(self.ids('?status=none'), {self.gamma.id})
        self.assertEqual(self.ids('?status=trialing'), {self.beta.id})
        self.assertEqual(self.ids('?plan=pro_t'), {self.acme.id, self.beta.id})
        self.assertEqual(self.ids('?ending_within=4'), {self.beta.id})

    def test_users_count_and_subscription(self):
        r = self.client.get('/api/admin/companies/?search=acme')
        row = r.data['results'][0]
        self.assertEqual(row['users_count'], 1)
        self.assertEqual(row['active_subscription']['plan_code'], 'pro_t')

    def test_query_count_does_not_grow_with_companies(self):
        def count():
            with CaptureQueriesContext(connection) as ctx:
                self.client.get('/api/admin/companies/')
            return len(ctx.captured_queries)

        before = count()
        for i in range(5):
            c = UserCompanies.objects.create(company_name=f'Extra {i}')
            CompanySubscription.objects.filter(company=c).delete()
            CompanySubscription.objects.create(
                company=c, subscription_plan=self.free, status='active',
                start_date=self.today, end_date=self.today + timedelta(days=30))
        self.assertEqual(count(), before)


class SubscriptionAuditTests(PlatformAdminTestBase):
    def test_assign_and_extend_are_audited_with_actor(self):
        r = self.client.post(f'/api/admin/companies/{self.gamma.id}/subscription/',
                             {'subscription_plan': self.pro.id}, format='json')
        self.assertEqual(r.status_code, 201)
        log = AuditLog.objects.filter(company=self.gamma, action='ASSIGN').get()
        self.assertEqual(log.user, self.owner)
        self.assertEqual(log.new_data['plan'], 'pro_t')

        new_end = (self.today + timedelta(days=400)).isoformat()
        r = self.client.put(f'/api/admin/companies/{self.gamma.id}/subscription/',
                            {'end_date': new_end}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data['end_date'], new_end)
        log = (AuditLog.objects.filter(company=self.gamma, action='UPDATE',
                                       user=self.owner).latest('timestamp'))
        self.assertEqual(log.new_data['end_date'], new_end)
        self.assertNotEqual(log.previous_data['end_date'], new_end)

    def test_end_before_start_rejected(self):
        r = self.client.put(f'/api/admin/companies/{self.acme.id}/subscription/',
                            {'end_date': (self.today - timedelta(days=60)).isoformat()},
                            format='json')
        self.assertEqual(r.status_code, 400)

    def test_history(self):
        r = self.client.get(f'/api/admin/companies/{self.acme.id}/subscription/')
        self.assertEqual(len(r.data), 1)


class PlanFeatureTests(PlatformAdminTestBase):
    def test_subscriber_count(self):
        r = self.client.get(f'/api/admin/plans/{self.pro.id}/')
        self.assertEqual(r.data['subscriber_count'], 2)

    def test_limits_must_be_object(self):
        f = Feature.objects.create(code='users_t', name='Users')
        pf = PlanFeature.objects.create(subscription_plan=self.pro, feature=f)
        r = self.client.put(f'/api/admin/plans/{self.pro.id}/features/{pf.id}/',
                            {'limits': [1, 2]}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_feature_delete_guard(self):
        f = Feature.objects.create(code='guarded_t', name='Guarded')
        PlanFeature.objects.create(subscription_plan=self.pro, feature=f)
        r = self.client.delete(f'/api/admin/features/{f.id}/')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.data['plans'], ['pro_t'])
        r = self.client.delete(f'/api/admin/features/{f.id}/?force=1')
        self.assertEqual(r.status_code, 204)
        self.assertFalse(Feature.objects.filter(pk=f.pk).exists())

    def test_feature_code_is_immutable(self):
        f = Feature.objects.create(code='fixed_t', name='Fixed')
        r = self.client.patch(f'/api/admin/features/{f.id}/', {'code': 'other'},
                              format='json')
        self.assertEqual(r.status_code, 400)
        r = self.client.patch(f'/api/admin/features/{f.id}/', {'name': 'Renamed'},
                              format='json')
        self.assertEqual(r.status_code, 200)


class AuditLogTests(PlatformAdminTestBase):
    def test_filters_and_pagination(self):
        AuditLog.objects.all().delete()
        AuditLog.objects.create(company=self.acme, user=self.owner, action='UPDATE',
                                resource_type='PLAN', resource_id='1')
        AuditLog.objects.create(company=None, user=None, action='DELETE',
                                resource_type='FEATURE', resource_id='2')
        r = self.client.get('/api/admin/audit-log/')
        self.assertEqual(r.data['count'], 2)
        r = self.client.get('/api/admin/audit-log/?resource_type=PLAN')
        self.assertEqual([l['resource_type'] for l in r.data['results']], ['PLAN'])
        self.assertEqual(r.data['results'][0]['company_name'], 'Acme Traders')
        r = self.client.get('/api/admin/audit-log/?user=own')
        self.assertEqual(r.data['count'], 1)
        r = self.client.get(f'/api/admin/audit-log/?date_from={self.today + timedelta(days=1)}')
        self.assertEqual(r.data['count'], 0)
        self.assertEqual(self.client.get('/api/admin/audit-log/?date_from=bad').status_code, 400)
        r = self.client.get('/api/admin/audit-log/facets/')
        self.assertEqual(r.data['resource_types'], ['FEATURE', 'PLAN'])
