"""Raw Razorpay diagnostics — no error translation, no interpretation.

    python manage.py razorpay_debug

Talks to api.razorpay.com directly with `requests` and prints the exact HTTP
status and response body for each call. Use this when `sync_razorpay_plans`
reports an error you do not believe: the SDK collapses unrecognised error codes
into `ServerError`, which hides what actually happened.

Read-only by default. `--create-plan` performs one real plan creation.
"""
import json

import requests
from django.conf import settings
from django.core.management.base import BaseCommand

BASE = 'https://api.razorpay.com/v1'


class Command(BaseCommand):
    help = "Print raw Razorpay API responses for diagnosis."

    def add_arguments(self, parser):
        parser.add_argument('--create-plan', action='store_true',
                            help="Actually attempt to create a ₹1 test plan.")
        parser.add_argument('--timeout', type=int, default=20)

    def _show(self, label, response):
        ok = 200 <= response.status_code < 300
        style = self.style.SUCCESS if ok else self.style.ERROR
        self.stdout.write(style(f"\n{label}  →  HTTP {response.status_code}"))
        try:
            body = response.json()
            self.stdout.write(json.dumps(body, indent=2)[:1500])
            error = body.get('error') if isinstance(body, dict) else None
            # Razorpay usually returns {"error": {"code": …, "description": …}},
            # but product-gate rejections return a bare {"error": "Unauthorized"}.
            if isinstance(error, dict):
                self.stdout.write(self.style.WARNING(
                    f"  code        : {error.get('code')}\n"
                    f"  description : {error.get('description')}\n"
                    f"  reason      : {error.get('reason')}\n"
                    f"  source      : {error.get('source')}\n"
                    f"  step        : {error.get('step')}"))
            elif error:
                self.stdout.write(self.style.WARNING(
                    f"  error (plain string) : {error}\n"
                    "  No {code, description} envelope — this is the product "
                    "gateway rejecting the route, not a field-level error."))
        except ValueError:
            self.stdout.write(response.text[:1000])
        return ok

    def handle(self, *args, **options):
        key_id = getattr(settings, 'RAZORPAY_KEY_ID', '')
        key_secret = getattr(settings, 'RAZORPAY_KEY_SECRET', '')
        if not key_id or not key_secret:
            self.stderr.write(self.style.ERROR("Keys are not configured in .env"))
            return

        auth = (key_id, key_secret)
        timeout = options['timeout']
        self.stdout.write(f"key_id     : {key_id}")
        self.stdout.write(f"mode       : {'TEST' if key_id.startswith('rzp_test_') else 'LIVE'}")
        self.stdout.write(f"secret len : {len(key_secret)}")

        # 1. Does auth work at all? /payments is always available.
        try:
            r = requests.get(f"{BASE}/payments", auth=auth, params={'count': 1},
                             timeout=timeout)
        except Exception as exc:  # noqa: BLE001
            self.stderr.write(self.style.ERROR(
                f"Network failure reaching Razorpay: {type(exc).__name__}: {exc}"))
            return
        auth_ok = self._show("GET /payments (auth check)", r)
        if not auth_ok:
            self.stdout.write(self.style.ERROR(
                "\nAuthentication is failing. Everything else will fail too. "
                "Verify the key/secret pair in the Razorpay dashboard."))
            return

        # 2. Is the Subscriptions product reachable?
        r = requests.get(f"{BASE}/plans", auth=auth, params={'count': 100},
                         timeout=timeout)
        plans_ok = self._show("GET /plans (Subscriptions access)", r)

        if plans_ok:
            items = r.json().get('items', [])
            self.stdout.write(f"\nExisting plans on this account: {len(items)}")
            for item in items:
                notes = item.get('notes') or {}
                detail = item.get('item') or {}
                self.stdout.write(
                    f"  {item['id']}  {item.get('period'):8} "
                    f"{detail.get('amount')} {detail.get('currency')}  "
                    f"{detail.get('name')}  notes={notes}")
        else:
            self.stdout.write(self.style.ERROR(
                "\n/plans is not accessible. The usual cause is that the "
                "Subscriptions product has not been activated on this account "
                "(Dashboard → Subscriptions). The 'description' field above is "
                "Razorpay's own explanation — trust it over any message the app "
                "prints."))

        # 3. Optionally try a real create.
        if options['create_plan']:
            payload = {
                'period': 'monthly', 'interval': 1,
                'item': {'name': 'debug probe plan', 'amount': 100,
                         'currency': 'INR', 'description': 'safe to ignore'},
                'notes': {'purpose': 'razorpay_debug probe'},
            }
            self.stdout.write("\nPOST /plans payload:")
            self.stdout.write(json.dumps(payload, indent=2))
            r = requests.post(f"{BASE}/plans", auth=auth, json=payload,
                              timeout=timeout)
            self._show("POST /plans (create probe)", r)
        else:
            self.stdout.write(self.style.WARNING(
                "\nSkipped plan creation. Re-run with --create-plan to test it."))
