"""Apply downgrades whose effective date has arrived.

Schedule this daily, alongside expire_subscriptions:

    5 2 * * * cd /path/to/invoice_api && python manage.py apply_scheduled_plan_changes >> logs/billing.log 2>&1

Idempotent — running it twice in a day is harmless.
"""
from django.core.management.base import BaseCommand

from billing.services import apply_due_scheduled_changes


class Command(BaseCommand):
    help = "Apply scheduled plan downgrades that are now due."

    def handle(self, *args, **options):
        applied = apply_due_scheduled_changes()
        if not applied:
            self.stdout.write("No scheduled plan changes due.")
            return
        for change in applied:
            self.stdout.write(self.style.SUCCESS(
                f"  company={change.company_id} "
                f"{change.from_plan.code} → {change.to_plan.code}"))
        self.stdout.write(self.style.SUCCESS(f"Applied {len(applied)} change(s)."))
