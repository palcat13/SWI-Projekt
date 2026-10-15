from datetime import datetime, timedelta

from django.db.models import Q, QuerySet
from django.utils import timezone

from .models import Reservation, ReservationStatus

APPROVAL_WINDOW = timedelta(hours=24)


def deadline_for(reservation: Reservation, now: datetime) -> datetime:
    return min(now + APPROVAL_WINDOW, reservation.start_at)


def live_pending_q(now: datetime) -> Q:
    return Q(status=ReservationStatus.PENDING_APPROVAL, approval_deadline__gt=now)


def overdue_queryset(now: datetime | None = None) -> QuerySet:
    now = now or timezone.now()
    return Reservation.objects.filter(
        status=ReservationStatus.PENDING_APPROVAL, approval_deadline__lte=now
    )
