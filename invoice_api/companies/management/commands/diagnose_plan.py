"""
Why is this company resolving to the wrong plan?

    python manage.py diagnose_plan --company 9
    python manage.py diagnose_plan --user aarti --watch 5 --for 120

Prints, side by side, the three layers that decide a company's features —
the database rows, the cached subscription, and the cached plan features —
and flags where they disagree. `--watch` polls so you can catch an
intermittent flip in the act.

Read the output like this:

  DB says pro, cache says free       → stale cache; invalidation didn't reach
                                        this process (see the CACHE BACKEND note)
  cache holds {} (no subscription)   → the negative-cache path; something saw
                                        zero working subscriptions for 60s
  plan resolves but features empty   → `plan_features:<id>` cached empty, or
                                        the plan genuinely has no PlanFeature rows
  DB itself says free                → not a cache problem; something wrote it
"""
import os
import time
from datetime import date

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Diagnose plan/feature resolution for a company across DB and cache layers."

    def add_arguments(self, parser):
        parser.add_argument('--company', help='UserCompanies id or exact name')
        parser.add_argument('--user', help='username or email')
        parser.add_argument('--watch', type=int, default=0,
                            help='re-check every N seconds')
        parser.add_argument('--for', type=int, default=60, dest='duration',
                            help='with --watch, stop after N seconds (default 60)')
        parser.add_argument('--clear', action='store_true',
                            help='delete this company\'s cached subscription and exit')

    def handle(self, *args, **opts):
        company = self.resolve_company(opts)

        self.report_backend()

        if opts['clear']:
            cache.delete(f'company_sub:{company.id}')
            self.stdout.write(self.style.SUCCESS(
                f'Cleared company_sub:{company.id} — in THIS process only if the '
                'backend is LocMemCache.'))
            return

        self.report_db(company)

        if not opts['watch']:
            self.report_resolved(company)
            return

        deadline = time.time() + opts['duration']
        last = None
        while time.time() < deadline:
            snapshot = self.report_resolved(company, compact=True)
            if last is not None and snapshot != last:
                self.stdout.write(self.style.ERROR(
                    '  ^^^ CHANGED — this is the flip you are chasing'))
            last = snapshot
            time.sleep(opts['watch'])

    # ── target ────────────────────────────────────────────────────────

    def resolve_company(self, opts):
        from accounts.models import User, UserCompanies

        if opts['company']:
            ident = opts['company']
            co = (UserCompanies.objects.filter(pk=ident).first()
                  if str(ident).isdigit() else None)
            co = co or UserCompanies.objects.filter(company_name=ident).first()
            if not co:
                raise CommandError(f'No company matches {ident!r}.')
            return co

        if opts['user']:
            ident = opts['user']
            user = (User.objects.filter(username=ident).first()
                    or User.objects.filter(email__iexact=ident).first())
            if not user:
                raise CommandError(f'No user matches {ident!r}.')
            if not user.user_company:
                raise CommandError(f'{user.username} has no company.')
            return user.user_company

        raise CommandError('Pass --company <id|name> or --user <username|email>.')

    # ── layers ────────────────────────────────────────────────────────

    def report_backend(self):
        backend = settings.CACHES['default']['BACKEND'] if hasattr(
            settings, 'CACHES') else 'django.core.cache.backends.locmem.LocMemCache'
        self.stdout.write(self.style.MIGRATE_HEADING('CACHE BACKEND'))
        self.stdout.write(f'  {backend}')
        self.stdout.write(f'  pid {os.getpid()}')

        if 'locmem' in backend.lower():
            self.stdout.write(self.style.ERROR(
                '  LocMemCache is per-process and per-container.\n'
                '  cache.delete() in a signal only clears the ONE worker that ran it;\n'
                '  every other worker keeps serving the stale plan until its own TTL\n'
                '  expires (company_sub = up to 3600s, user_perms = up to 300s).\n'
                '  Two identical requests can therefore return different plans.\n'
                '  NOTE: this command runs in its own process, so what it sees is not\n'
                '  what your web workers see. Compare it against the live API response.'))
        if 'dummy' in backend.lower():
            self.stdout.write(self.style.WARNING(
                '  DummyCache caches nothing — every request hits the DB.'))

    def report_db(self, company):
        from companies.models import CompanySubscription, PlanFeature

        today = timezone.localdate()
        self.stdout.write(self.style.MIGRATE_HEADING(
            f'\nDATABASE — {company.company_name} (id {company.id})'))
        self.stdout.write(f'  localdate(): {today}   TIME_ZONE={settings.TIME_ZONE}')

        rows = (CompanySubscription.objects.filter(company=company)
                .select_related('subscription_plan')
                .order_by('-start_date', '-id'))
        if not rows:
            self.stdout.write(self.style.ERROR('  no subscription rows at all'))
            return

        live_statuses = ('active', 'trialing', 'past_due')
        live = []
        for s in rows:
            working = s.is_working()
            marker = ''
            if s.status in live_statuses and s.start_date <= today:
                live.append(s)
                marker = '  <-- candidate'
            self.stdout.write(
                f'  id={s.id:<5} {s.subscription_plan.code:<11} {s.status:<10} '
                f'{s.start_date} -> {s.end_date}  is_working={working}{marker}')

        if len(live) > 1:
            plans = {s.subscription_plan.code for s in live}
            starts = {s.start_date for s in live}
            self.stdout.write(self.style.ERROR(
                f'  {len(live)} rows match the resolver filter '
                f'(status in {live_statuses}, start_date <= today).'))
            if len(plans) > 1:
                self.stdout.write(self.style.ERROR(
                    f'  They are DIFFERENT plans {sorted(plans)} — the resolver picks by\n'
                    '  order_by("-start_date").first() with no tiebreaker, so the winner\n'
                    '  is whatever order the DB returns.'))
            if len(starts) < len(live):
                self.stdout.write(self.style.ERROR(
                    '  Two candidates share a start_date — the ordering CANNOT break\n'
                    '  that tie deterministically.'))
            self.stdout.write(self.style.WARNING(
                '  Note the unique constraint only covers active/trialing, so a\n'
                '  past_due row is allowed to coexist with an active one.'))

        # plan feature rows for whichever plan would win
        if live:
            plan = live[0].subscription_plan
            codes = sorted(PlanFeature.objects
                           .filter(subscription_plan=plan)
                           .values_list('feature__code', flat=True))
            self.stdout.write(f'\n  PlanFeature rows for {plan.code!r}: '
                              f'{codes or "NONE"}')
            if not codes:
                self.stdout.write(self.style.ERROR(
                    '  This plan has NO features in the DB — it will behave like Free\n'
                    '  no matter what the subscription says.'))

    def report_resolved(self, company, compact=False):
        from invoice_api.middleware import (get_active_subscription,
                                            get_enabled_features)

        sub_key = f'company_sub:{company.id}'
        cached = cache.get(sub_key)

        resolved = get_active_subscription(company)
        features = sorted(get_enabled_features(resolved))
        plan_code = (resolved or {}).get('plan_code')

        feat_key = (f"plan_features:{resolved['plan_id']}"
                    if resolved and resolved.get('plan_id') else None)
        cached_feats = cache.get(feat_key) if feat_key else None

        stamp = timezone.localtime().strftime('%H:%M:%S')

        if compact:
            self.stdout.write(
                f'  {stamp}  plan={plan_code or "NONE":<11} '
                f'features={len(features):<2} {features}')
        else:
            self.stdout.write(self.style.MIGRATE_HEADING('\nRESOLVED (this process)'))
            self.stdout.write(f'  {sub_key} in cache before this call: '
                              f'{"MISS" if cached is None else cached}')
            self.stdout.write(f'  get_active_subscription() -> {resolved}')
            self.stdout.write(f'  plan_code                 -> {plan_code or "NONE"}')
            self.stdout.write(f'  {feat_key or "plan_features:—"} cached: '
                              f'{"MISS" if cached_feats is None else sorted(cached_feats)}')
            self.stdout.write(f'  get_enabled_features()    -> {features or "EMPTY"}')

            if resolved == {}:
                self.stdout.write(self.style.ERROR(
                    '\n  Subscription resolved to {} — the negative-cache path.\n'
                    '  Either no row passed the filter, or is_working() was False.\n'
                    '  This is cached for MISS_CACHE_TTL = 60s, during which every\n'
                    '  feature gate behaves as Free.'))
            elif not features:
                self.stdout.write(self.style.ERROR(
                    f'\n  Plan {plan_code!r} resolved but features are EMPTY.\n'
                    '  Check the PlanFeature rows above; if they exist, then\n'
                    f'  {feat_key} is holding a stale empty set (cached for up to 3600s).'))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f'\n  This process currently resolves {plan_code!r} '
                    f'with {len(features)} features.'))
                self.stdout.write(
                    '  If the live API disagrees, the difference is the cache — '
                    'they are separate processes.')

        return (plan_code, tuple(features))
