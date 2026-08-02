"""Billing regression tests.

The Razorpay client is patched throughout, so these run offline and in CI.
Run with:

    python manage.py test billing
"""
import hashlib
import hmac
import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import (CompanyPermission, CompanyRole, User,
                             UserCompanies)
from companies.models import (CompanySubscription, Feature, PlanFeature,
                              SubscriptionPlan)

from .models import (BillingSubscription, PaymentRecord, RazorpayPlan,
                     ScheduledPlanChange, WebhookEvent, to_paise)

WEBHOOK_SECRET = 'test_webhook_secret'
KEY_ID = 'rzp_test_TKYQ2afloTOVR0'
KEY_SECRET = 'test_key_secret'


def sign(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@override_settings(RAZORPAY_KEY_ID=KEY_ID, RAZORPAY_KEY_SECRET=KEY_SECRET,
                   RAZORPAY_WEBHOOK_SECRET=WEBHOOK_SECRET)
class BillingTestBase(TestCase):

    def setUp(self):
        # The companies app seeds free/pro/enterprise in migration 0007, so
        # take whatever is there and pin the prices this suite expects.
        self.free = self._plan('free', 'Free', 0, 0)
        self.pro = self._plan('pro', 'Pro', 499, 4999)
        self.enterprise = self._plan('enterprise', 'Enterprise', 1999, 19999)

        feature, _ = Feature.objects.get_or_create(
            code='invoicing', defaults={'name': 'Invoicing'})
        for plan in (self.free, self.pro, self.enterprise):
            PlanFeature.objects.get_or_create(
                subscription_plan=plan, feature=feature, defaults={'limits': {}})

        self.company = UserCompanies.objects.create(company_name='Acme')
        self.other_company = UserCompanies.objects.create(company_name='Rival')

        self.user = User.objects.create_user(
            username='admin', email='admin@acme.test', password='pw12345!')
        self.user.user_company = self.company
        self.user.save()

        self._set_entitlement(self.free)
        self._grant('subscription.view', 'subscription.manage')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    @staticmethod
    def _plan(code, name, monthly, yearly):
        plan, _ = SubscriptionPlan.objects.get_or_create(
            code=code, defaults={'name': name})
        plan.name = name
        plan.monthly_price = monthly
        plan.yearly_price = yearly
        plan.is_active = True
        plan.save()
        return plan

    def _set_entitlement(self, plan, days=365, status='active'):
        """A signal may already have created a Free subscription for the new
        company; mutate it rather than inserting a second active row."""
        today = timezone.localdate()
        existing = (CompanySubscription.objects.filter(company=self.company)
                    .order_by('-start_date').first())
        if existing:
            existing.subscription_plan = plan
            existing.start_date = today
            existing.end_date = today + timedelta(days=days)
            existing.status = status
            existing.save()
            return existing
        return CompanySubscription.objects.create(
            company=self.company, subscription_plan=plan, start_date=today,
            end_date=today + timedelta(days=days), status=status)

    def _grant(self, *codes):
        role, _ = CompanyRole.objects.get_or_create(
            company=self.company, name='Company Admin')
        for code in codes:
            perm, _ = CompanyPermission.objects.get_or_create(
                code=code, company=None,
                defaults={'name': code, 'is_system_permission': True,
                          'permission_type': 'CUSTOM'})
            role.permissions.add(perm)
        role.users.add(self.user)

    def entitlement(self):
        return (CompanySubscription.objects.filter(company=self.company)
                .order_by('-start_date').first())


# ---------------------------------------------------------------------------
# Webhook security & idempotency — the part that must never regress
# ---------------------------------------------------------------------------

class WebhookSecurityTests(BillingTestBase):
    url = '/api/billing/webhook/razorpay/'

    def _event(self, event='subscription.activated', sub_id='sub_TEST1',
               status='active', extra=None):
        now = int(timezone.now().timestamp())
        entity = {
            'id': sub_id, 'entity': 'subscription', 'plan_id': 'plan_TEST1',
            'customer_id': 'cust_TEST1', 'status': status,
            'current_start': now, 'current_end': now + 30 * 86400,
            'charge_at': now + 30 * 86400, 'paid_count': 1, 'total_count': 120,
        }
        entity.update(extra or {})
        return {'entity': 'event', 'event': event,
                'payload': {'subscription': {'entity': entity}},
                'created_at': now}

    def _post(self, body: dict, signature=None, event_id='evt_1'):
        raw = json.dumps(body).encode()
        return self.client.post(
            self.url, data=raw, content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE=signature if signature is not None
            else sign(WEBHOOK_SECRET, raw),
            HTTP_X_RAZORPAY_EVENT_ID=event_id)

    def test_unsigned_request_is_rejected_and_changes_nothing(self):
        response = self._post(self._event(), signature='')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(WebhookEvent.objects.count(), 0)

    def test_bad_signature_is_rejected(self):
        response = self._post(self._event(), signature='deadbeef')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(WebhookEvent.objects.count(), 0)

    def test_signature_over_tampered_body_is_rejected(self):
        body = self._event()
        raw = json.dumps(body).encode()
        good = sign(WEBHOOK_SECRET, raw)
        body['payload']['subscription']['entity']['plan_id'] = 'plan_ATTACKER'
        tampered = json.dumps(body).encode()
        response = self.client.post(
            self.url, data=tampered, content_type='application/json',
            HTTP_X_RAZORPAY_SIGNATURE=good, HTTP_X_RAZORPAY_EVENT_ID='evt_x')
        self.assertEqual(response.status_code, 400)

    @override_settings(RAZORPAY_WEBHOOK_SECRET='')
    def test_missing_secret_refuses_rather_than_trusting(self):
        response = self._post(self._event(), signature='anything')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(WebhookEvent.objects.count(), 0)

    def test_replayed_event_is_processed_once(self):
        sub = self._billing_subscription()
        body = self._event(sub_id=sub.razorpay_subscription_id)

        first = self._post(body, event_id='evt_dupe')
        second = self._post(body, event_id='evt_dupe')

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()['status'], 'duplicate')
        self.assertEqual(WebhookEvent.objects.filter(event_id='evt_dupe').count(), 1)

    def test_unknown_event_type_is_recorded_but_ignored(self):
        response = self._post({'entity': 'event', 'event': 'payout.processed',
                               'payload': {}, 'created_at': 1},
                              event_id='evt_ignore')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(WebhookEvent.objects.get(event_id='evt_ignore').status,
                         'ignored')

    def _billing_subscription(self, plan=None, status='created'):
        return BillingSubscription.objects.create(
            company=self.company, subscription_plan=plan or self.pro,
            period='monthly', razorpay_subscription_id='sub_TEST1',
            razorpay_plan_id='plan_TEST1', status=status, total_count=120)


# ---------------------------------------------------------------------------
# Entitlement state machine
# ---------------------------------------------------------------------------

class EntitlementTests(WebhookSecurityTests):

    def test_activation_grants_the_plan_and_sets_end_date(self):
        self._billing_subscription()
        response = self._post(self._event(status='active'), event_id='evt_act')
        self.assertEqual(response.status_code, 200)

        entitlement = self.entitlement()
        self.assertEqual(entitlement.subscription_plan, self.pro)
        self.assertEqual(entitlement.status, 'active')
        self.assertTrue(entitlement.is_working())

    def test_created_status_grants_nothing(self):
        """A mandate that has not been charged must not unlock the plan."""
        self._billing_subscription()
        self._post(self._event(event='subscription.authenticated',
                               status='authenticated'), event_id='evt_auth')
        self.assertEqual(self.entitlement().subscription_plan, self.free)

    def test_halted_moves_to_past_due_not_straight_to_free(self):
        self._billing_subscription(status='active')
        self._post(self._event(event='subscription.halted', status='halted'),
                   event_id='evt_halt')
        entitlement = self.entitlement()
        self.assertEqual(entitlement.status, 'past_due')
        self.assertEqual(entitlement.subscription_plan, self.pro)

    def test_cancellation_reverts_to_free(self):
        self._billing_subscription(status='active')
        self._post(self._event(status='active'), event_id='evt_a')
        self.assertEqual(self.entitlement().subscription_plan, self.pro)

        self._post(self._event(event='subscription.cancelled', status='cancelled'),
                   event_id='evt_c')
        self.assertEqual(self.entitlement().subscription_plan, self.free)

    def test_only_one_active_entitlement_row_survives(self):
        """The partial unique constraint must never be violated by a re-grant."""
        self._billing_subscription()
        self._post(self._event(status='active'), event_id='evt_1')
        self._post(self._event(status='active'), event_id='evt_2')
        self.assertEqual(
            CompanySubscription.objects.filter(
                company=self.company, status__in=['active', 'trialing']).count(), 1)

    def test_charged_event_records_the_payment_once(self):
        sub = self._billing_subscription(status='active')
        now = int(timezone.now().timestamp())
        body = self._event(event='subscription.charged', status='active')
        body['payload']['payment'] = {'entity': {
            'id': 'pay_TEST1', 'amount': 49900, 'currency': 'INR',
            'status': 'captured', 'method': 'card', 'created_at': now,
            'invoice_id': 'inv_TEST1'}}

        self._post(body, event_id='evt_charge')
        self._post(body, event_id='evt_charge')  # replay

        self.assertEqual(PaymentRecord.objects.filter(
            razorpay_payment_id='pay_TEST1').count(), 1)
        payment = PaymentRecord.objects.get(razorpay_payment_id='pay_TEST1')
        self.assertEqual(payment.company, self.company)
        self.assertEqual(payment.amount_paise, 49900)
        self.assertEqual(str(payment.amount_rupees), '499')

    def test_webhook_for_unknown_subscription_does_not_crash(self):
        response = self._post(self._event(sub_id='sub_NOT_OURS'),
                              event_id='evt_unknown')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.entitlement().subscription_plan, self.free)


# ---------------------------------------------------------------------------
# API surface: scoping, permissions, no client-supplied amounts
# ---------------------------------------------------------------------------

class BillingAPITests(BillingTestBase):

    def test_plans_endpoint_marks_the_current_plan(self):
        response = self.client.get('/api/billing/plans/')
        self.assertEqual(response.status_code, 200)
        by_code = {p['code']: p for p in response.json()['plans']}
        self.assertTrue(by_code['free']['is_current'])
        self.assertFalse(by_code['pro']['is_current'])

    def test_status_endpoint_never_leaks_the_key_secret(self):
        response = self.client.get('/api/billing/subscription/')
        payload = json.dumps(response.json())
        self.assertIn('razorpay_key_id', payload)
        self.assertNotIn(KEY_SECRET, payload)

    def test_payment_history_is_scoped_to_the_callers_company(self):
        PaymentRecord.objects.create(
            company=self.company, razorpay_payment_id='pay_MINE',
            amount_paise=49900, status='captured')
        PaymentRecord.objects.create(
            company=self.other_company, razorpay_payment_id='pay_THEIRS',
            amount_paise=999900, status='captured')

        response = self.client.get('/api/billing/payments/')
        body = response.json()
        ids = [r['razorpay_payment_id'] for r in (
            body['results'] if isinstance(body, dict) else body)]
        self.assertEqual(ids, ['pay_MINE'])

    def test_subscribe_ignores_any_amount_in_the_request_body(self):
        # Plans are provisioned ahead of time, so the price is fixed in the
        # mapping before the customer ever reaches checkout.
        RazorpayPlan.objects.create(
            subscription_plan=self.pro, period='monthly',
            razorpay_plan_id='plan_PRO_M', amount_paise=to_paise(499))

        with patch('billing.services.get_client') as mock:
            client = MagicMock()
            client.subscription.create.return_value = {
                'id': 'sub_NEW', 'status': 'created',
                'short_url': 'https://rzp.io/x', 'total_count': 120}
            mock.return_value = client

            response = self.client.post('/api/billing/subscribe/', {
                'plan_code': 'pro', 'period': 'monthly',
                'amount': 1, 'total_final_amount': 1,   # attacker input
            }, format='json')

        self.assertEqual(response.status_code, 201)
        payload = client.subscription.create.call_args[0][0]
        # Razorpay is told which plan, never how much — the amount lives on the
        # plan, which came from the database.
        self.assertEqual(payload['plan_id'], 'plan_PRO_M')
        self.assertNotIn('amount', payload)
        self.assertEqual(
            RazorpayPlan.objects.get(razorpay_plan_id='plan_PRO_M').amount_paise,
            to_paise(self.pro.monthly_price))

    def test_subscribe_rejects_the_free_plan(self):
        response = self.client.post('/api/billing/subscribe/',
                                    {'plan_code': 'free', 'period': 'monthly'},
                                    format='json')
        self.assertEqual(response.status_code, 400)

    def test_subscribe_rejects_an_unknown_plan(self):
        response = self.client.post('/api/billing/subscribe/',
                                    {'plan_code': 'platinum', 'period': 'monthly'},
                                    format='json')
        self.assertEqual(response.status_code, 400)

    def test_verify_rejects_another_companys_subscription_id(self):
        BillingSubscription.objects.create(
            company=self.other_company, subscription_plan=self.pro,
            period='monthly', razorpay_subscription_id='sub_THEIRS',
            razorpay_plan_id='plan_x', status='created')

        response = self.client.post('/api/billing/verify/', {
            'razorpay_payment_id': 'pay_1',
            'razorpay_subscription_id': 'sub_THEIRS',
            'razorpay_signature': 'whatever'}, format='json')
        self.assertEqual(response.status_code, 404)

    def test_verify_rejects_a_forged_signature(self):
        BillingSubscription.objects.create(
            company=self.company, subscription_plan=self.pro, period='monthly',
            razorpay_subscription_id='sub_MINE', razorpay_plan_id='plan_x',
            status='created')
        response = self.client.post('/api/billing/verify/', {
            'razorpay_payment_id': 'pay_1',
            'razorpay_subscription_id': 'sub_MINE',
            'razorpay_signature': 'forged'}, format='json')
        self.assertEqual(response.status_code, 400)

    def test_write_endpoints_require_subscription_manage(self):
        viewer = User.objects.create_user(
            username='viewer', email='v@acme.test', password='pw12345!')
        viewer.user_company = self.company
        viewer.save()
        role = CompanyRole.objects.create(company=self.company, name='Viewer')
        perm = CompanyPermission.objects.get(code='subscription.view')
        role.permissions.add(perm)
        role.users.add(viewer)

        client = APIClient()
        client.force_authenticate(viewer)

        self.assertEqual(client.get('/api/billing/plans/').status_code, 200)
        self.assertEqual(
            client.post('/api/billing/subscribe/',
                        {'plan_code': 'pro', 'period': 'monthly'},
                        format='json').status_code, 403)
        self.assertEqual(
            client.post('/api/billing/cancel/', {}, format='json').status_code, 403)

    def test_admin_endpoints_are_closed_to_tenant_admins(self):
        for path in ('/api/admin/billing/health/',
                     '/api/admin/billing/subscriptions/',
                     '/api/admin/billing/payments/'):
            self.assertEqual(self.client.get(path).status_code, 403, path)


# ---------------------------------------------------------------------------
# Plan changes
# ---------------------------------------------------------------------------

class PlanChangeTests(BillingTestBase):

    def _live_pro(self):
        today = timezone.localdate()
        CompanySubscription.objects.filter(company=self.company).update(
            subscription_plan=self.pro, status='active',
            start_date=today - timedelta(days=10),
            end_date=today + timedelta(days=20))
        RazorpayPlan.objects.create(
            subscription_plan=self.pro, period='monthly',
            razorpay_plan_id='plan_PRO_M', amount_paise=to_paise(499))
        return BillingSubscription.objects.create(
            company=self.company, subscription_plan=self.pro, period='monthly',
            razorpay_subscription_id='sub_LIVE', razorpay_plan_id='plan_PRO_M',
            status='active', total_count=120,
            current_end=timezone.now() + timedelta(days=20))

    def test_upgrade_applies_immediately(self):
        self._live_pro()
        RazorpayPlan.objects.create(
            subscription_plan=self.enterprise, period='monthly',
            razorpay_plan_id='plan_ENT_M', amount_paise=to_paise(1999))
        with patch('billing.services.get_client') as mock:
            client = MagicMock()
            mock.return_value = client
            response = self.client.post(
                '/api/billing/change-plan/',
                {'plan_code': 'enterprise', 'period': 'monthly'}, format='json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['effect'], 'upgraded')
        self.assertEqual(self.entitlement().subscription_plan, self.enterprise)
        self.assertEqual(
            client.subscription.edit.call_args[0][1]['schedule_change_at'], 'now')
        client.plan.create.assert_not_called()

    def test_downgrade_is_scheduled_and_does_not_change_access_today(self):
        live = self._live_pro()
        RazorpayPlan.objects.create(
            subscription_plan=self.enterprise, period='monthly',
            razorpay_plan_id='plan_ENT_M', amount_paise=to_paise(1999))
        live.subscription_plan = self.enterprise
        live.save()
        CompanySubscription.objects.filter(company=self.company).update(
            subscription_plan=self.enterprise)

        with patch('billing.services.get_client') as mock:
            client = MagicMock()
            client.plan.create.return_value = {'id': 'plan_PRO_M'}
            mock.return_value = client
            response = self.client.post(
                '/api/billing/change-plan/',
                {'plan_code': 'pro', 'period': 'monthly'}, format='json')

        self.assertEqual(response.json()['effect'], 'downgrade_scheduled')
        # Access is unchanged until the period ends.
        self.assertEqual(self.entitlement().subscription_plan, self.enterprise)
        change = ScheduledPlanChange.objects.get(company=self.company,
                                                 status='pending')
        self.assertEqual(change.to_plan, self.pro)
        self.assertEqual(
            client.subscription.edit.call_args[0][1]['schedule_change_at'],
            'cycle_end')

    def test_due_scheduled_change_is_applied_and_is_idempotent(self):
        from .services import apply_due_scheduled_changes
        today = timezone.localdate()
        ScheduledPlanChange.objects.create(
            company=self.company, from_plan=self.enterprise, to_plan=self.pro,
            period='monthly', effective_date=today - timedelta(days=1))

        self.assertEqual(len(apply_due_scheduled_changes()), 1)
        self.assertEqual(self.entitlement().subscription_plan, self.pro)
        self.assertEqual(len(apply_due_scheduled_changes()), 0)

    def test_future_scheduled_change_is_not_applied_early(self):
        from .services import apply_due_scheduled_changes
        ScheduledPlanChange.objects.create(
            company=self.company, from_plan=self.pro, to_plan=self.free,
            period='monthly',
            effective_date=timezone.localdate() + timedelta(days=5))
        self.assertEqual(len(apply_due_scheduled_changes()), 0)

    def test_cancel_at_cycle_end_keeps_access_until_period_end(self):
        self._live_pro()
        with patch('billing.services.get_client') as mock:
            mock.return_value = MagicMock()
            response = self.client.post('/api/billing/cancel/',
                                        {'at_cycle_end': True}, format='json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.entitlement().subscription_plan, self.pro)
        self.assertTrue(ScheduledPlanChange.objects.filter(
            company=self.company, to_plan=self.free, status='pending').exists())

    def test_immediate_cancel_drops_to_free_now(self):
        self._live_pro()
        with patch('billing.services.get_client') as mock:
            mock.return_value = MagicMock()
            self.client.post('/api/billing/cancel/', {'at_cycle_end': False},
                             format='json')
        self.assertEqual(self.entitlement().subscription_plan, self.free)

    def test_preview_reports_direction_and_credit(self):
        self._live_pro()
        response = self.client.get(
            '/api/billing/preview/?plan_code=enterprise&period=monthly')
        body = response.json()
        self.assertEqual(body['direction'], 'upgrade')
        self.assertEqual(body['days_remaining'], 20)
        self.assertGreater(float(body['unused_credit']), 0)


# ---------------------------------------------------------------------------
# Plan sync
# ---------------------------------------------------------------------------

class RazorpayFailureTests(BillingTestBase):
    """Razorpay saying no must never reach the user as a 500 traceback."""

    def _rzp_bad_request(self, message):
        import razorpay.errors as rzp_errors
        return rzp_errors.BadRequestError(message)

    def test_rate_limit_returns_429_with_guidance_not_a_500(self):
        RazorpayPlan.objects.create(
            subscription_plan=self.pro, period='monthly',
            razorpay_plan_id='plan_PRO_M', amount_paise=to_paise(499))
        with patch('billing.services.get_client') as mock:
            client = MagicMock()
            client.subscription.create.side_effect = self._rzp_bad_request(
                "Too many requests")
            mock.return_value = client
            response = self.client.post(
                '/api/billing/subscribe/',
                {'plan_code': 'pro', 'period': 'monthly'}, format='json')

        self.assertEqual(response.status_code, 429)
        self.assertTrue(response.json()['retryable'])
        self.assertIn('rate-limiting', response.json()['detail'])

    def test_subscriptions_not_enabled_returns_503_with_the_fix(self):
        RazorpayPlan.objects.create(
            subscription_plan=self.pro, period='monthly',
            razorpay_plan_id='plan_PRO_M', amount_paise=to_paise(499))
        with patch('billing.services.get_client') as mock:
            client = MagicMock()
            client.subscription.create.side_effect = self._rzp_bad_request(
                "The requested URL was not found on the server.")
            mock.return_value = client
            response = self.client.post(
                '/api/billing/subscribe/',
                {'plan_code': 'pro', 'period': 'monthly'}, format='json')

        self.assertEqual(response.status_code, 503)
        self.assertIn('Subscriptions product is not enabled',
                      response.json()['detail'])

    def test_checkout_never_creates_a_plan(self):
        """Plan creation on the customer path is what trips the rate limit."""
        with patch('billing.services.get_client') as mock:
            client = MagicMock()
            client.plan.all.return_value = {'items': []}   # nothing to adopt
            mock.return_value = client
            response = self.client.post(
                '/api/billing/subscribe/',
                {'plan_code': 'pro', 'period': 'monthly'}, format='json')

        client.plan.create.assert_not_called()
        client.subscription.create.assert_not_called()
        self.assertEqual(response.status_code, 503)
        self.assertIn('sync_razorpay_plans', response.json()['detail'])

    def test_checkout_adopts_an_orphan_plan_instead_of_creating_one(self):
        """A plan left on the account by a failed run is reused, not duplicated."""
        with patch('billing.services.get_client') as mock:
            client = MagicMock()
            client.plan.all.return_value = {'items': [{
                'id': 'plan_ORPHAN', 'period': 'monthly',
                'item': {'amount': to_paise(499)},
                'notes': {'plan_code': 'pro', 'period': 'monthly'},
            }]}
            client.subscription.create.return_value = {
                'id': 'sub_NEW', 'status': 'created',
                'short_url': 'https://rzp.io/x', 'total_count': 120}
            mock.return_value = client
            response = self.client.post(
                '/api/billing/subscribe/',
                {'plan_code': 'pro', 'period': 'monthly'}, format='json')

        client.plan.create.assert_not_called()
        self.assertEqual(response.status_code, 201)
        self.assertTrue(RazorpayPlan.objects.filter(
            razorpay_plan_id='plan_ORPHAN', subscription_plan=self.pro).exists())

    def test_a_failed_subscribe_leaves_no_half_built_state(self):
        RazorpayPlan.objects.create(
            subscription_plan=self.pro, period='monthly',
            razorpay_plan_id='plan_PRO_M', amount_paise=to_paise(499))
        with patch('billing.services.get_client') as mock:
            client = MagicMock()
            client.subscription.create.side_effect = self._rzp_bad_request(
                "Too many requests")
            mock.return_value = client
            self.client.post('/api/billing/subscribe/',
                             {'plan_code': 'pro', 'period': 'monthly'},
                             format='json')

        self.assertEqual(BillingSubscription.objects.count(), 0)
        self.assertEqual(self.entitlement().subscription_plan, self.free)

    def test_server_error_preserves_razorpays_own_description(self):
        """The SDK buckets every unrecognised error code into ServerError, so
        the description is the only real signal. It must never be discarded."""
        import razorpay.errors as rzp_errors
        RazorpayPlan.objects.create(
            subscription_plan=self.pro, period='monthly',
            razorpay_plan_id='plan_PRO_M', amount_paise=to_paise(499))
        with patch('billing.services.get_client') as mock:
            client = MagicMock()
            client.subscription.create.side_effect = rzp_errors.ServerError(
                "Subscription is not enabled for this merchant")
            mock.return_value = client
            response = self.client.post(
                '/api/billing/subscribe/',
                {'plan_code': 'pro', 'period': 'monthly'}, format='json')

        detail = response.json()['detail']
        self.assertIn("Subscription is not enabled for this merchant", detail)
        self.assertNotIn("having trouble on their end", detail)

    def test_empty_error_description_says_so_instead_of_guessing(self):
        import razorpay.errors as rzp_errors
        RazorpayPlan.objects.create(
            subscription_plan=self.pro, period='monthly',
            razorpay_plan_id='plan_PRO_M', amount_paise=to_paise(499))
        with patch('billing.services.get_client') as mock:
            client = MagicMock()
            client.subscription.create.side_effect = rzp_errors.ServerError("")
            mock.return_value = client
            response = self.client.post(
                '/api/billing/subscribe/',
                {'plan_code': 'pro', 'period': 'monthly'}, format='json')

        self.assertIn('no description', response.json()['detail'])

    def test_bare_unauthorized_blames_the_product_gate_not_the_keys(self):
        """/payments returns 200 with the same key while /plans returns 401 —
        so a bare "Unauthorized" means Subscriptions is not activated. Telling
        the user to re-check working credentials sends them the wrong way."""
        import razorpay.errors as rzp_errors
        RazorpayPlan.objects.create(
            subscription_plan=self.pro, period='monthly',
            razorpay_plan_id='plan_PRO_M', amount_paise=to_paise(499))
        with patch('billing.services.get_client') as mock:
            client = MagicMock()
            client.subscription.create.side_effect = rzp_errors.ServerError(
                "Unauthorized")
            mock.return_value = client
            response = self.client.post(
                '/api/billing/subscribe/',
                {'plan_code': 'pro', 'period': 'monthly'}, format='json')

        detail = response.json()['detail']
        self.assertEqual(response.status_code, 503)
        self.assertIn('not activated', detail)
        self.assertNotIn('Check RAZORPAY_KEY_ID', detail)

    def test_bad_credentials_are_named_as_such(self):
        import razorpay.errors as rzp_errors
        RazorpayPlan.objects.create(
            subscription_plan=self.pro, period='monthly',
            razorpay_plan_id='plan_PRO_M', amount_paise=to_paise(499))
        with patch('billing.services.get_client') as mock:
            client = MagicMock()
            client.subscription.create.side_effect = rzp_errors.ServerError(
                "Authentication failed")
            mock.return_value = client
            response = self.client.post(
                '/api/billing/subscribe/',
                {'plan_code': 'pro', 'period': 'monthly'}, format='json')

        self.assertEqual(response.status_code, 503)
        self.assertIn('RAZORPAY_KEY_ID', response.json()['detail'])

    def test_network_failure_is_a_502_not_a_500(self):
        RazorpayPlan.objects.create(
            subscription_plan=self.pro, period='monthly',
            razorpay_plan_id='plan_PRO_M', amount_paise=to_paise(499))
        with patch('billing.services.get_client') as mock:
            client = MagicMock()
            client.subscription.create.side_effect = ConnectionError("no route")
            mock.return_value = client
            response = self.client.post(
                '/api/billing/subscribe/',
                {'plan_code': 'pro', 'period': 'monthly'}, format='json')

        self.assertEqual(response.status_code, 502)
        self.assertTrue(response.json()['retryable'])


class PlanSyncTests(BillingTestBase):

    def test_free_plans_are_never_pushed_to_razorpay(self):
        from .services import sync_all_plans
        with patch('billing.services.get_client') as mock:
            client = MagicMock()
            client.plan.create.side_effect = [
                {'id': 'plan_A'}, {'id': 'plan_B'}, {'id': 'plan_C'}, {'id': 'plan_D'}]
            mock.return_value = client
            report = sync_all_plans()

        skipped = [r for r in report if r[0] == 'free']
        self.assertTrue(all('skipped' in str(r[2]) for r in skipped))
        self.assertEqual(client.plan.create.call_count, 4)  # pro + ent, 2 periods

    def test_price_change_creates_a_new_plan_and_retires_the_old(self):
        from .services import ensure_razorpay_plan
        with patch('billing.services.get_client') as mock:
            client = MagicMock()
            client.plan.create.return_value = {'id': 'plan_V1'}
            mock.return_value = client
            first = ensure_razorpay_plan(self.pro, 'monthly')

            # Same price → no second call to Razorpay.
            again = ensure_razorpay_plan(self.pro, 'monthly')
            self.assertEqual(first.pk, again.pk)
            self.assertEqual(client.plan.create.call_count, 1)

            self.pro.monthly_price = 599
            self.pro.save()
            client.plan.create.return_value = {'id': 'plan_V2'}
            second = ensure_razorpay_plan(self.pro, 'monthly')

        self.assertNotEqual(first.pk, second.pk)
        first.refresh_from_db()
        self.assertFalse(first.is_active)
        self.assertTrue(second.is_active)
        self.assertEqual(second.amount_paise, 59900)

    def test_to_paise_uses_decimal_not_float(self):
        from decimal import Decimal
        self.assertEqual(to_paise(Decimal('499.99')), 49999)
        self.assertEqual(to_paise(Decimal('0.1') + Decimal('0.2')), 30)
