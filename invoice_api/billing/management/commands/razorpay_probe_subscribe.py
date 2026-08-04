"""
Reproduce the exact `subscription.create` call and show Razorpay's FULL error.

    python manage.py razorpay_probe_subscribe --plan pro --period monthly

Why this exists: the Razorpay Python SDK raises
`BadRequestError(json['error']['description'])` and throws the rest of the
body away. When Razorpay replies

    {"error": {"code": "BAD_REQUEST_ERROR",
               "description": "Validation failed",
               "field": "total_count"}}

the SDK — and therefore your API and your logs — only ever sees
"Validation failed". The offending field is the one piece of information
you actually need, so this command bypasses the SDK and posts with
`requests`, printing the raw JSON.

It also pre-checks the things that produce "Validation failed" without a
round trip: a plan mapping pointing at a plan id that no longer exists in
the account, and a `total_count` above Razorpay's per-period ceiling.

Creating a subscription does NOT charge anyone — no money moves until the
customer authorises the mandate — but it is a real object in a LIVE
account, so pass --cancel to remove it again.
"""
import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

API = 'https://api.razorpay.com/v1'


class Command(BaseCommand):
    help = ("Attempt a real Razorpay subscription create and print the full "
            "error body, including the field the SDK hides.")

    def add_arguments(self, parser):
        parser.add_argument('--plan', default='pro', dest='plan_code',
                            help='local SubscriptionPlan code (default: pro)')
        parser.add_argument('--period', default='monthly',
                            choices=['monthly', 'yearly'])
        parser.add_argument('--cancel', action='store_true',
                            help='cancel the subscription again if it is created')
        parser.add_argument('--dry-run', action='store_true',
                            help='run the local pre-checks only, call nothing')
        parser.add_argument('--bisect', action='store_true',
                            help='when Razorpay says "Validation failed" without '
                                 'naming a field, retry from a minimal payload and '
                                 'add one parameter at a time to find the culprit')

    def handle(self, *args, **opts):
        try:
            import requests
        except ImportError as exc:
            raise CommandError('The `requests` package is required.') from exc

        from billing.models import MAX_TOTAL_COUNT, TOTAL_COUNT, RazorpayPlan
        from companies.models import SubscriptionPlan

        key_id = getattr(settings, 'RAZORPAY_KEY_ID', '')
        key_secret = getattr(settings, 'RAZORPAY_KEY_SECRET', '')
        if not key_id or not key_secret:
            raise CommandError('RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set.')

        code, period = opts['plan_code'], opts['period']
        w, ok, err, warn = (self.stdout.write, self.style.SUCCESS,
                            self.style.ERROR, self.style.WARNING)
        auth = (key_id, key_secret)
        live = not key_id.startswith('rzp_test')

        w(self.style.MIGRATE_HEADING(
            f'Probing {code}/{period} against '
            f'{"LIVE" if live else "TEST"} account {key_id[:14]}…'))

        # ── local mapping ──
        plan = SubscriptionPlan.objects.filter(code=code, is_active=True).first()
        if not plan:
            raise CommandError(f'No active local SubscriptionPlan with code {code!r}.')
        mapping = RazorpayPlan.objects.filter(
            subscription_plan=plan, period=period, is_active=True).first()
        if not mapping:
            w(err(f'  No RazorpayPlan mapping for {code}/{period}.'))
            w(err('  Checkout calls ensure_razorpay_plan(allow_create=False), so it\n'
                  '  cannot create one on demand. Run: manage.py sync_razorpay_plans'))
            return
        w(f'  local mapping    : {mapping.razorpay_plan_id} '
          f'({mapping.amount_paise} paise)')

        total_count = TOTAL_COUNT[period]
        w(f'  total_count      : {total_count}')

        # ── pre-check 1: total_count ceiling ──
        cap = MAX_TOTAL_COUNT.get(period)
        if cap and total_count > cap:
            w(err(f'\n  PROBLEM: total_count={total_count} exceeds Razorpay\'s maximum '
                  f'of {cap} for a {period} plan.'))
            w(err('  Razorpay reports this as nothing more than "Validation failed".\n'
                  f'  Fix: set TOTAL_COUNT[{period!r}] to {cap} or lower in '
                  'billing/models.py.'))
        else:
            w(ok(f'  total_count within the {period} ceiling '
                 f'({total_count} <= {cap})'))

        # ── pre-check 2: does the plan still exist upstream? ──
        if opts['dry_run']:
            w(warn('\n  --dry-run: stopping before any network call.'))
            return

        r = requests.get(f'{API}/plans/{mapping.razorpay_plan_id}', auth=auth, timeout=20)
        if r.status_code == 200:
            body = r.json()
            w(ok(f'  plan exists upstream: {body.get("period")}/'
                 f'{body.get("interval")} '
                 f'{body.get("item", {}).get("amount")} '
                 f'{body.get("item", {}).get("currency")}'))
            if body.get('period') != period:
                w(err(f'  MISMATCH: upstream plan period is {body.get("period")!r} '
                      f'but we are subscribing as {period!r}.'))
        else:
            w(err(f'  plan {mapping.razorpay_plan_id} NOT found upstream '
                  f'(HTTP {r.status_code}).'))
            w(err(self._pretty(r)))
            w(err('  The stored mapping points at a plan that does not exist in this\n'
                  '  account — typically a mapping created against a different (test)\n'
                  '  account, or a plan deleted in the dashboard.\n'
                  '  Fix: manage.py sync_razorpay_plans'))
            return

        # ── the real call ──
        payload = {
            'plan_id': mapping.razorpay_plan_id,
            'total_count': total_count,
            'quantity': 1,
            'customer_notify': 1,
            'notes': {'purpose': 'razorpay_probe_subscribe — safe to cancel'},
        }
        w(self.style.MIGRATE_HEADING('\nPOST /v1/subscriptions'))
        w(json.dumps(payload, indent=2))

        r = requests.post(f'{API}/subscriptions', auth=auth, json=payload, timeout=30)
        w(f'\n  HTTP {r.status_code}')

        if r.status_code in (200, 201):
            body = r.json()
            w(ok(f'  SUCCESS — subscription {body["id"]} created, '
                 f'status={body.get("status")}'))
            w('  So the payload itself is valid. If /billing/subscribe/ still fails,\n'
              '  the difference is upstream of this call — most likely\n'
              '  ensure_razorpay_plan() resolving a different mapping.')
            if opts['cancel']:
                c = requests.post(f'{API}/subscriptions/{body["id"]}/cancel',
                                  auth=auth, json={'cancel_at_cycle_end': 0},
                                  timeout=30)
                w(('  cancelled' if c.status_code == 200
                   else f'  could not cancel (HTTP {c.status_code}) — '
                        f'remove {body["id"]} in the dashboard'))
            else:
                w(warn(f'  Left in place. Cancel {body["id"]} in the dashboard, '
                       'or re-run with --cancel.'))
            return

        # ── the payoff: the full error body ──
        w(err('  FAILED. Razorpay\'s full response — this is what the SDK hides:'))
        w(err(self._pretty(r)))

        try:
            error = r.json().get('error', {})
        except ValueError:
            return
        field = error.get('field')
        if field:
            w(err(f'\n  Offending field: {field!r}'))
            hint = {
                'total_count': (f'Must be <= {cap} for a {period} plan; '
                                f'you are sending {total_count}. '
                                f'Edit TOTAL_COUNT in billing/models.py.'),
                'plan_id': ('The plan id does not exist in this account, or belongs '
                            'to the other (test/live) account. Run '
                            'sync_razorpay_plans.'),
                'customer_notify': 'Must be 0 or 1.',
                'quantity': 'Must be a positive integer.',
            }.get(field)
            if hint:
                w(err(f'  {hint}'))
        else:
            w(warn('\n  Razorpay named no field.'))
            if opts['bisect']:
                self.bisect(requests, auth, mapping.razorpay_plan_id, period,
                            total_count, opts['cancel'])
            else:
                w(warn('  Re-run with --bisect to find the offending parameter '
                       'empirically.'))

    # ── bisect ────────────────────────────────────────────────────────

    def bisect(self, requests, auth, plan_id, period, total_count, cancel):
        """Add one parameter at a time until Razorpay rejects the request.

        Razorpay sometimes returns "Validation failed" with no `field`, which
        leaves nothing to read. Building the payload up from the documented
        minimum turns that into a bisection: the first variant that fails
        names the culprit by construction.
        """
        w, ok, err, warn = (self.stdout.write, self.style.SUCCESS,
                            self.style.ERROR, self.style.WARNING)
        w(self.style.MIGRATE_HEADING('\nBISECTING the payload'))
        w('  Each line is a real POST. Successes are cancelled immediately.\n')

        base = {'plan_id': plan_id, 'total_count': total_count}
        variants = [
            ('plan_id + total_count only', base),
            ('total_count=1', {**base, 'total_count': 1}),
            ('total_count=12', {**base, 'total_count': 12}),
            ('+ quantity=1', {**base, 'quantity': 1}),
            ('+ customer_notify=1', {**base, 'customer_notify': 1}),
            ('+ notes (plain ascii)', {**base, 'notes': {'purpose': 'probe'}}),
            # the earlier attempt carried an em-dash; Razorpay is fussy about
            # non-ASCII in notes, so prove whether that alone is fatal
            ('+ notes (non-ascii em-dash)', {**base, 'notes': {'purpose': 'probe — x'}}),
            ('full payload as start_subscription sends it', {
                **base, 'quantity': 1, 'customer_notify': 1,
                'notes': {'company_id': '1', 'company_name': 'Probe Co',
                          'plan_code': 'pro', 'period': period}}),
        ]

        first_failure = None
        for label, payload in variants:
            r = requests.post(f'{API}/subscriptions', auth=auth,
                              json=payload, timeout=30)
            if r.status_code in (200, 201):
                sid = r.json()['id']
                w(ok(f'  OK    {label}  -> {sid}'))
                c = requests.post(f'{API}/subscriptions/{sid}/cancel', auth=auth,
                                  json={'cancel_at_cycle_end': 0}, timeout=30)
                if c.status_code != 200:
                    w(warn(f'        could not cancel {sid} — remove it in the dashboard'))
            else:
                try:
                    detail = r.json().get('error', {})
                except ValueError:
                    detail = {'raw': r.text[:200]}
                desc = detail.get('description', '?')
                fld = f" field={detail['field']!r}" if detail.get('field') else ''
                w(err(f'  FAIL  {label}  ({r.status_code}: {desc}{fld})'))
                if first_failure is None:
                    first_failure = (label, payload, detail)

        w(self.style.MIGRATE_HEADING('\nCONCLUSION'))
        if first_failure is None:
            w(ok('  Every variant was accepted, including the full payload.'))
            w('  So the request start_subscription builds is valid. The failure you\n'
              '  saw through /billing/subscribe/ must come from something around the\n'
              '  call rather than the call itself — check the server log for the\n'
              '  "billing: Razorpay ..." line, which records the raw description.')
        elif first_failure[0] == 'plan_id + total_count only':
            w(err('  Even the minimal documented payload is rejected, so no parameter\n'
                  '  is at fault — this is account-level. Most likely Subscriptions is\n'
                  '  not fully activated for LIVE mode on this account (test and live\n'
                  '  are enabled separately, and live often needs Razorpay support).\n'
                  '  Confirm with: manage.py verify_razorpay --probe-subscriptions'))
        else:
            label, payload, detail = first_failure
            w(err(f'  First variant to fail: {label}'))
            w(err(f'  Razorpay said: {detail}'))
            w('  The parameter introduced by that variant is the culprit — every\n'
              '  simpler payload above it was accepted.')

    @staticmethod
    def _pretty(response):
        try:
            return '  ' + json.dumps(response.json(), indent=2).replace('\n', '\n  ')
        except ValueError:
            return '  ' + (response.text or '(empty body)')[:800]
