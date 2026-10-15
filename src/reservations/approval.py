from abc import ABC, abstractmethod
from datetime import datetime, timedelta

from django.db.models import Q

from .models import Companion, Reservation, ReservationStatus

DEFAULT_WINDOW = timedelta(hours=24)


class ApprovalPolicy(ABC):
    @abstractmethod
    def requires_approval(self, companion: Companion) -> bool:
        ...

    @abstractmethod
    def deadline_for(self, reservation: Reservation, now: datetime) -> datetime:
        ...

    @abstractmethod
    def is_live(self, reservation: Reservation, now: datetime) -> bool:
        ...

    @abstractmethod
    def live_q(self, now: datetime) -> Q:
        ...

    @abstractmethod
    def overdue_q(self, now: datetime) -> Q:
        ...


class FixedWindowApprovalPolicy(ApprovalPolicy):
    def __init__(self, window: timedelta = DEFAULT_WINDOW):
        self.window = window

    def requires_approval(self, companion: Companion) -> bool:
        return companion.requires_approval

    def deadline_for(self, reservation: Reservation, now: datetime) -> datetime:
        return min(now + self.window, reservation.start_at)

    def is_live(self, reservation: Reservation, now: datetime) -> bool:
        return (
            reservation.status == ReservationStatus.PENDING_APPROVAL
            and reservation.approval_deadline is not None
            and reservation.approval_deadline > now
        )

    def live_q(self, now: datetime) -> Q:
        return Q(
            status=ReservationStatus.PENDING_APPROVAL,
            approval_deadline__isnull=False,
            approval_deadline__gt=now,
        )

    def overdue_q(self, now: datetime) -> Q:
        return Q(status=ReservationStatus.PENDING_APPROVAL) & (
            Q(approval_deadline__isnull=True) | Q(approval_deadline__lte=now)
        )


_policy: ApprovalPolicy = FixedWindowApprovalPolicy()


def get_policy() -> ApprovalPolicy:
    return _policy


def set_policy(policy: ApprovalPolicy) -> ApprovalPolicy:
    global _policy
    previous = _policy
    _policy = policy
    return previous


def effective_status(
    reservation: Reservation, now: datetime, policy: ApprovalPolicy | None = None
) -> str:
    policy = policy or get_policy()
    if reservation.status != ReservationStatus.PENDING_APPROVAL:
        return reservation.status
    if policy.is_live(reservation, now):
        return ReservationStatus.PENDING_APPROVAL
    return ReservationStatus.EXPIRED
