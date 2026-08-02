"""Live connectivity check against Razorpay. Run this locally first.

    python manage.py verify_razorpay

Confirms, in order:
  1. credentials are present in the environment
  2. they authenticate against api.razorpay.com
  3. the Subscriptions product is enabled on the account
  4. the webhook secret is configured and signature verification works

Creates nothing permanent — the throwaway plan it makes to test Subscriptions
is left in your Razorpay test dashboard (Razorpay has no plan-delete API) and
is clearly named so you can ignore it.
"""
import json
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from billing.razorpay_client import (RazorpayNotConfigured, get_client,
                                     is_test_mode, verify_webhook_signature)


class Command(BaseCommand):
    help = "Check Razorpay credentials, Subscriptions access and webhook secret."

    def add_arguments(self, parser):
        parser.add_argument(
            '--probe-subscriptions', action='store_true',
            help="Create a throwaway ₹1 plan to prove Subscriptions is enabled.")

    def _ok(self, msg):
        self.stdout.write(self.style.SUCCESS(f"  PASS  {msg}"))

    def _fail(self, msg):
        self.stdout.write(self.style.ERROR(f"  FAIL  {msg}"))

    def _warn(self, msg):
        self.stdout.write(self.style.WARNING(f"  WARN  {msg}"))

    def handle(self, *args, **options):
        self.stdout.write("Razorpay configuration check\n")

        key_id = getattr(settings, 'RAZORPAY_KEY_ID', '')
        key_secret = getattr(settings, 'RAZORPAY_KEY_SECRET', '')

        # 1. credentials present
        if not key_id or not key_secret:
            self._fail("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set in .env")
            return
        self._ok(f"credentials present (key_id={key_id[:12]}…)")
        self.stdout.write(
            f"        mode: {'TEST' if is_test_mode() else 'LIVE'}")
        if not is_test_mode():
            self._warn("These are LIVE keys. Real money will move.")

        # 2. authenticate against a product every account has
        try:
            client = get_client()
            client.payment.all({'count': 1})
        except RazorpayNotConfigured as exc:
            self._fail(str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            self._fail(f"credentials rejected on /payments: {exc}")
            self.stdout.write(
                "        The key/secret pair itself is wrong, or api.razorpay.com "
                "is unreachable. Run `manage.py razorpay_debug` for the raw "
                "response.")
            return
        self._ok("credentials authenticate (GET /payments succeeded)")

        # 3. is the Subscriptions product actually provisioned?
        try:
            plans = client.plan.all({'count': 3})
        except Exception as exc:  # noqa: BLE001
            self._fail(f"Subscriptions API rejected the same credentials: {exc}")
            self.stdout.write(
                "        /payments works but /plans does not, so this is NOT a key "
                "problem — the Subscriptions product is not activated on this "
                "account.\n"
                "        Activate it at Dashboard → Subscriptions. Test accounts "
                "often need Razorpay support to switch it on.\n"
                "        `manage.py razorpay_debug` shows the raw 200 vs 401.")
            return
        self._ok(f"Subscriptions reachable — account has {plans.get('count', 0)} plan(s)")

        for item in plans.get('items', [])[:3]:
            self.stdout.write(
                f"        {item['id']}  {item['period']}  "
                f"{item['item']['amount']} {item['item']['currency']}  "
                f"{item['item']['name']}")

        # 3. Subscriptions enabled
        if options['probe_subscriptions']:
            try:
                probe = client.plan.create({
                    'period': 'monthly', 'interval': 1,
                    'item': {'name': f"__connectivity_probe_{int(time.time())}",
                             'amount': 100, 'currency': 'INR'},
                    'notes': {'purpose': 'verify_razorpay probe — safe to ignore'},
                })
                self._ok(f"Subscriptions enabled (created probe plan {probe['id']})")
            except Exception as exc:  # noqa: BLE001
                self._fail(f"Subscriptions may not be enabled: {exc}")
                self.stdout.write(
                    "        Enable it at Dashboard → Subscriptions, then re-run.")
        else:
            self._warn("skipped Subscriptions probe (pass --probe-subscriptions)")

        # 4. webhook secret
        secret = getattr(settings, 'RAZORPAY_WEBHOOK_SECRET', '')
        if not secret:
            self._fail("RAZORPAY_WEBHOOK_SECRET not set — webhooks will be rejected")
            self.stdout.write(
                "        Set one in Dashboard → Settings → Webhooks, then put the "
                "same value in .env as RAZORPAY_WEBHOOK_SECRET.")
        else:
            body = json.dumps({'event': 'ping'}).encode()
            import hashlib
            import hmac
            sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            if verify_webhook_signature(body, sig):
                self._ok("webhook secret configured and signature check works")
            else:
                self._fail("webhook signature self-test failed")

        # 5. local plan mappings
        from billing.models import RazorpayPlan
        mapped = RazorpayPlan.objects.filter(is_active=True).count()
        stale = [p.razorpay_plan_id for p in
                 RazorpayPlan.objects.filter(is_active=True)
                 .select_related('subscription_plan') if p.is_stale]
        if mapped == 0:
            self._warn("no local plans mapped yet — run `manage.py sync_razorpay_plans`")
        else:
            self._ok(f"{mapped} plan mapping(s) stored locally")
        if stale:
            self._warn(f"{len(stale)} mapping(s) stale after a price change: "
                       f"{', '.join(stale)} — re-run sync_razorpay_plans")
