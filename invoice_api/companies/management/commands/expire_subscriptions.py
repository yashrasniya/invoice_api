"""
Daily subscription expiry job (run via cron or celery beat):

    python manage.py expire_subscriptions

- trialing past end_date          → Free plan (soft lock: data stays readable, paid features stop)
- active past end_date            → past_due (auto_renew) or expired
- past_due past grace period     → expired
- clears company_sub cache for every touched company (natural expiry fires
  no signal, so this job is what invalidates the cache).
"""
from datetime import timedelta

from django.core.cache import cache
from django.core.management.base import BaseCommand
from django.utils import timezone

from billing.services import revert_to_free
from companies.models import CompanySubscription


class Command(BaseCommand):
    help = "Expire subscriptions past end_date / grace period and clear caches."

    def handle(self, *args, **options):
        today = timezone.localdate()  # UTC date expires plans ~5.5h early in IST
        grace = timedelta(days=CompanySubscription.GRACE_PERIOD_DAYS)
        touched_companies = set()

        # an unpaid trial has no mandate to retry, so it skips past_due and lands on Free
        for sub in CompanySubscription.objects.filter(status='trialing', end_date__lt=today):
            if revert_to_free(sub.company) is None:
                sub.status = 'expired'
                sub.save(update_fields=['status', 'updated_at'])
            touched_companies.add(sub.company_id)

        # active past end_date
        ended = CompanySubscription.objects.filter(status='active', end_date__lt=today)
        for sub in ended:
            sub.status = 'past_due' if sub.auto_renew else 'expired'
            sub.save(update_fields=['status', 'updated_at'])
            touched_companies.add(sub.company_id)

        # past_due beyond grace
        overdue = CompanySubscription.objects.filter(
            status='past_due', end_date__lt=today - grace)
        for sub in overdue:
            sub.status = 'expired'
            sub.save(update_fields=['status', 'updated_at'])
            touched_companies.add(sub.company_id)

        for company_id in touched_companies:
            cache.delete(f"company_sub:{company_id}")

        self.stdout.write(self.style.SUCCESS(
            f"Expired/downgraded subscriptions for {len(touched_companies)} companies."))
