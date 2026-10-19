"""15-day trial: grant, one-per-company, expiry to Free, mid-trial subscribe.

    python manage.py test companies.tests_trial
"""
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from accounts.models import UserCompanies
from companies.models import CompanySubscription, SubscriptionPlan
from companies.trial import TRIAL_DAYS, start_trial, start_trial_or_free, trial_days_left


def plan(code, monthly=0):
    p, _ = SubscriptionPlan.objects.get_or_create(code=code, defaults={'name': code.title()})
    p.monthly_price, p.yearly_price, p.is_active = monthly, monthly * 10, True
    p.save()
    return p


class TrialTests(TestCase):
    def setUp(self):
        self.free = plan('free')
        self.pro = plan('pro', 499)
        CompanySubscription.objects.all().delete()
        self.company = UserCompanies.objects.create(company_name='Acme')
        CompanySubscription.objects.filter(company=self.company).delete()
        UserCompanies.objects.filter(pk=self.company.pk).update(trial_used_at=None)
        self.company.refresh_from_db()

    def test_new_company_gets_15_day_pro_trial(self):
        sub = start_trial_or_free(self.company)
        today = timezone.localdate()
        self.assertEqual(sub.status, 'trialing')
        self.assertEqual(sub.subscription_plan, self.pro)
        self.assertEqual(sub.end_date, today + timedelta(days=TRIAL_DAYS))
        self.assertEqual(trial_days_left(sub), TRIAL_DAYS)
        self.company.refresh_from_db()
        self.assertIsNotNone(self.company.trial_used_at)
        self.assertTrue(sub.is_working())

    def test_signal_starts_trial_on_company_creation(self):
        with self.captureOnCommitCallbacks(execute=True):
            c = UserCompanies.objects.create(company_name='Fresh')
        sub = CompanySubscription.objects.get(company=c)
        self.assertEqual(sub.status, 'trialing')

    def test_only_one_trial_per_company(self):
        start_trial(self.company)
        CompanySubscription.objects.filter(company=self.company).delete()
        self.assertIsNone(start_trial(self.company))
        sub = start_trial_or_free(self.company)
        self.assertEqual(sub.subscription_plan, self.free)

    def test_no_trial_without_pro_plan(self):
        self.pro.is_active = False
        self.pro.save()
        sub = start_trial_or_free(self.company)
        self.assertEqual(sub.subscription_plan, self.free)
        self.assertEqual(sub.status, 'active')

    def test_expiry_moves_unpaid_trial_to_free(self):
        sub = start_trial(self.company)
        sub.end_date = timezone.localdate() - timedelta(days=1)
        sub.save()
        call_command('expire_subscriptions', verbosity=0)
        rows = CompanySubscription.objects.filter(company=self.company)
        self.assertEqual(rows.count(), 1)
        row = rows.get()
        self.assertEqual((row.subscription_plan, row.status), (self.free, 'active'))
        self.company.refresh_from_db()
        self.assertIsNotNone(self.company.trial_used_at)  # still can't re-trial

    def test_unexpired_trial_is_untouched(self):
        sub = start_trial(self.company)
        call_command('expire_subscriptions', verbosity=0)
        sub.refresh_from_db()
        self.assertEqual(sub.status, 'trialing')

    def test_subscribe_mid_trial_defers_first_charge_to_trial_end(self):
        from billing import services
        sub = start_trial(self.company)
        client = MagicMock()
        client.subscription.create.return_value = {'id': 'sub_1', 'status': 'created'}
        rp = MagicMock(razorpay_plan_id='plan_1')
        with patch.object(services, 'get_client', return_value=client), \
                patch.object(services, 'ensure_razorpay_plan', return_value=rp), \
                patch.object(services, 'razorpay_call', side_effect=lambda f, p: f(p)):
            services.start_subscription(self.company, 'pro', 'monthly')
        payload = client.subscription.create.call_args[0][0]
        self.assertEqual(payload['start_at'], services._trial_start_at(sub))
        self.assertGreater(payload['start_at'], timezone.now().timestamp())

    def test_subscribe_without_trial_has_no_start_at(self):
        from billing import services
        CompanySubscription.objects.filter(company=self.company).delete()
        client = MagicMock()
        client.subscription.create.return_value = {'id': 'sub_2', 'status': 'created'}
        rp = MagicMock(razorpay_plan_id='plan_1')
        with patch.object(services, 'get_client', return_value=client), \
                patch.object(services, 'ensure_razorpay_plan', return_value=rp), \
                patch.object(services, 'razorpay_call', side_effect=lambda f, p: f(p)):
            services.start_subscription(self.company, 'pro', 'monthly')
        self.assertNotIn('start_at', client.subscription.create.call_args[0][0])


class TrialReminderTests(TestCase):
    def setUp(self):
        from accounts.models import User
        self.free, self.pro = plan('free'), plan('pro', 499)
        CompanySubscription.objects.all().delete()
        self.company = UserCompanies.objects.create(company_name='Acme')
        CompanySubscription.objects.filter(company=self.company).delete()
        UserCompanies.objects.filter(pk=self.company.pk).update(trial_used_at=None)
        self.company.refresh_from_db()
        # create_user() ignores extra kwargs, so link the users afterwards
        self.admin = User.objects.create_user(username='boss', email='boss@acme.test', password='x')
        self.admin.user_company, self.admin.is_company_admin = self.company, True
        self.admin.save()
        staff = User.objects.create_user(username='staff', email='staff@acme.test', password='x')
        staff.user_company = self.company
        staff.save()
        self.sub = start_trial(self.company)

    def run_on(self, days_left):
        from django.core import mail
        from companies.trial_reminders import send_trial_reminders
        today = self.sub.end_date - timedelta(days=days_left)
        mail.outbox.clear()
        with patch('companies.trial_reminders.send_push') as push:
            sent = send_trial_reminders(today=today)
        return sent, mail.outbox, push

    def test_nothing_before_day_12(self):
        sent, outbox, push = self.run_on(4)
        self.assertEqual(sent, {'3d': 0, 'final': 0})
        self.assertEqual(outbox, [])

    def test_day_12_reminds_admins_only_once(self):
        sent, outbox, push = self.run_on(3)
        self.assertEqual(sent['3d'], 1)
        self.assertEqual([m.to for m in outbox], [['boss@acme.test']])  # not the non-admin
        self.assertIn('3 days left', outbox[0].subject)
        push.assert_called_once()
        again, outbox, _ = self.run_on(3)
        self.assertEqual(again['3d'], 0)
        self.assertEqual(outbox, [])

    def test_catch_up_if_job_missed_day_12(self):
        sent, outbox, _ = self.run_on(1)
        self.assertEqual(sent['3d'], 1)
        self.assertIn('1 day left', outbox[0].subject)

    def test_final_day_reminder_is_separate(self):
        self.run_on(3)
        sent, outbox, _ = self.run_on(0)
        self.assertEqual(sent, {'3d': 0, 'final': 1})
        self.assertIn('ends today', outbox[0].subject)

    def test_skips_company_that_already_subscribed(self):
        from billing.models import BillingSubscription
        BillingSubscription.objects.create(
            company=self.company, subscription_plan=self.pro, period='monthly',
            razorpay_subscription_id='sub_x', razorpay_plan_id='plan_x', status='authenticated')
        sent, outbox, _ = self.run_on(3)
        self.assertEqual(sent, {'3d': 0, 'final': 0})

    def test_ignores_non_trial_subscriptions(self):
        self.sub.status = 'active'
        self.sub.save()
        sent, outbox, _ = self.run_on(3)
        self.assertEqual(sent, {'3d': 0, 'final': 0})
