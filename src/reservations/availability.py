from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from django.db.models import Q, QuerySet
from django.utils import timezone

from . import approval
from .models import Companion, Reservation, ReservationStatus


def blocking_reservations(
    companion: Companion,
    start_at: datetime,
    end_at: datetime,
    exclude_id: UUID | None = None,
    now: datetime | None = None,
    policy: approval.ApprovalPolicy | None = None,
) -> QuerySet:
    """Reservations of `companion` that block the half-open interval [start_at, end_at) (BR-01, BR-02)."""
    now = now or timezone.now()
    policy = policy or approval.get_policy()
    queryset = Reservation.objects.filter(
        companion=companion, start_at__lt=end_at, end_at__gt=start_at
    ).filter(Q(status=ReservationStatus.CONFIRMED) | policy.live_q(now))
    if exclude_id is not None:
        queryset = queryset.exclude(id=exclude_id)
    return queryset


@dataclass(frozen=True)
class AvailabilityAnswer:
    available: bool
    blocking_ids: list[UUID]


def assess(
    companion: Companion,
    start_at: datetime,
    end_at: datetime,
    now: datetime | None = None,
    policy: approval.ApprovalPolicy | None = None,
) -> AvailabilityAnswer:
    """The OP-02 verdict and the blocking list, taken from one query so they cannot disagree."""
    blocking_ids = list(
        blocking_reservations(companion, start_at, end_at, now=now, policy=policy).values_list(
            "id", flat=True
        )
    )
    return AvailabilityAnswer(companion.is_active and not blocking_ids, blocking_ids)


def is_available(
    companion: Companion,
    start_at: datetime,
    end_at: datetime,
    now: datetime | None = None,
    policy: approval.ApprovalPolicy | None = None,
) -> bool:
    return assess(companion, start_at, end_at, now=now, policy=policy).available
