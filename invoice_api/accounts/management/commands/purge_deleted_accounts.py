from django.core.management.base import BaseCommand

from accounts import deletion


class Command(BaseCommand):
    help = (f"Permanently delete accounts whose owner asked to be deleted more than {deletion.PURGE_AFTER_DAYS} days ago. "
            "Schedule it daily (cron).")

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help="list who would be deleted, change nothing")

    def handle(self, *args, dry_run=False, **options):
        users = list(deletion.due_for_purge())
        if not users:
            self.stdout.write("Nothing due for deletion.")
            return
        for user in users:
            if dry_run:
                self.stdout.write(f"would delete {user.username} (asked {user.deletion_requested_at:%Y-%m-%d})")
            else:
                self.stdout.write(f"deleted {deletion.purge_user(user)}")
