"""Daily job: remind trial companies 3 days before the end and on the last day.

    python manage.py send_trial_reminders

Schedule it right after `expire_subscriptions`.
"""
from django.core.management.base import BaseCommand

from companies.trial_reminders import send_trial_reminders


class Command(BaseCommand):
    help = "Send the day-12 and day-15 free-trial reminders (email + push) to company admins."

    def handle(self, *args, **options):
        sent = send_trial_reminders()
        self.stdout.write(self.style.SUCCESS(
            f"Trial reminders sent: {sent['3d']} (3 days left), {sent['final']} (last day)."))
