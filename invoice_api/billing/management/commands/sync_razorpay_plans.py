"""Push local SubscriptionPlans to Razorpay as Razorpay Plans.

Run once after deploying, and again whenever a plan price changes:

    python manage.py sync_razorpay_plans

Razorpay plans are immutable, so a price change creates a NEW Razorpay plan and
deactivates the old mapping. Companies already on a mandate keep their old
price until they change plan — which is the correct behaviour.
"""
from django.core.management.base import BaseCommand

from billing.razorpay_client import (BillingUnavailable, RazorpayNotConfigured,
                                     is_test_mode)
from billing.services import sync_all_plans


class Command(BaseCommand):
    help = "Create/refresh Razorpay plans for every priced subscription plan."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="Show what would be pushed without calling Razorpay.")

    def handle(self, *args, **options):
        if options['dry_run']:
            from billing.models import MONTHLY, YEARLY, price_for, to_paise
            from companies.models import SubscriptionPlan
            for plan in SubscriptionPlan.objects.filter(is_active=True).order_by('id'):
                for period in (MONTHLY, YEARLY):
                    amount = to_paise(price_for(plan, period))
                    verdict = 'skip (free)' if amount <= 0 else f"{amount} paise"
                    self.stdout.write(f"  {plan.code:12} {period:8} {verdict}")
            return

        try:
            report = sync_all_plans()
        except (RazorpayNotConfigured, BillingUnavailable) as exc:
            self.stderr.write(self.style.ERROR(str(exc)))
            return

        mode = 'TEST' if is_test_mode() else 'LIVE'
        self.stdout.write(self.style.WARNING(f"Razorpay mode: {mode}"))
        errors = 0
        for code, period, result in report:
            if str(result).startswith('ERROR'):
                errors += 1
                self.stdout.write(self.style.ERROR(f"  {code:12} {period:8} {result}"))
            elif result.startswith('skipped'):
                self.stdout.write(f"  {code:12} {period:8} {result}")
            else:
                self.stdout.write(self.style.SUCCESS(f"  {code:12} {period:8} {result}"))

        if errors:
            self.stderr.write(self.style.ERROR(f"\n{errors} plan(s) failed to sync."))
            self.stderr.write(self.style.WARNING(
                "The text above is Razorpay's own error description. If it is "
                "unclear, run `python manage.py razorpay_debug` for the raw HTTP "
                "status and response body with no interpretation in the way."))
        else:
            self.stdout.write(self.style.SUCCESS("All plans synced."))
