from django.core.management.base import BaseCommand

from reservations import lifecycle


class Command(BaseCommand):
    help = "Mark PENDING_APPROVAL reservations whose approval deadline has passed as EXPIRED."

    def handle(self, *args, **options):
        expired = lifecycle.expire_overdue_approvals()
        self.stdout.write(f"expired={expired}")
