from django.core.management.base import BaseCommand
from django.utils import timezone

from reservations.models import Reservation, ReservationStatus


class Command(BaseCommand):
    help = "Mark PENDING_APPROVAL reservations whose approval deadline has passed as EXPIRED."

    def handle(self, *args, **options):
        expired = Reservation.objects.filter(
            status=ReservationStatus.PENDING_APPROVAL, approval_deadline__lte=timezone.now()
        ).update(status=ReservationStatus.EXPIRED)
        self.stdout.write(f"expired={expired}")
