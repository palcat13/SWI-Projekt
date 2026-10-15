from dataclasses import dataclass
from datetime import datetime, timedelta

from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.utils import timezone

from . import approval, availability, notifications
from .models import Reservation, ReservationStatus

CONFIRMED_CANCEL_NOTICE = timedelta(hours=24)

CANCELLABLE_STATES = {
    ReservationStatus.DRAFT,
    ReservationStatus.PENDING_APPROVAL,
    ReservationStatus.CONFIRMED,
}

FORBIDDEN = "FORBIDDEN"
CONFLICT = "CONFLICT"


class TransitionRefused(Exception):
    def __init__(self, kind: str, code: str, detail: str):
        super().__init__(detail)
        self.kind = kind
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class TransitionOutcome:
    reservation: Reservation
    idempotent: bool = False


def _reload(reservation: Reservation) -> Reservation:
    return Reservation.objects.select_related("companion").get(pk=reservation.pk)


def _notify_after_commit(event: str, reservation: Reservation) -> None:
    transaction.on_commit(lambda: notifications.get_port().notify(event, reservation))


def _is_blocked(
    reservation: Reservation, now: datetime, policy: approval.ApprovalPolicy
) -> bool:
    return availability.blocking_reservations(
        reservation.companion,
        reservation.start_at,
        reservation.end_at,
        exclude_id=reservation.id,
        now=now,
        policy=policy,
    ).exists()


def confirm(
    reservation: Reservation,
    actor: AbstractBaseUser,
    now: datetime | None = None,
    policy: approval.ApprovalPolicy | None = None,
) -> TransitionOutcome:
    now = now or timezone.now()
    policy = policy or approval.get_policy()
    with transaction.atomic():
        reservation = _reload(reservation)
        if reservation.customer_id != actor.pk:
            raise TransitionRefused(
                FORBIDDEN, "FORBIDDEN_ACTOR", "Only the customer of the reservation can confirm it."
            )
        if reservation.status != ReservationStatus.DRAFT:
            raise TransitionRefused(
                CONFLICT, "INVALID_STATE", f"Reservation is {reservation.status}, not DRAFT."
            )
        if not reservation.companion.is_active:
            raise TransitionRefused(CONFLICT, "INACTIVE_RESOURCE", "The companion is not active.")
        if reservation.start_at <= now:
            raise TransitionRefused(
                CONFLICT, "PAST_INTERVAL", "The reservation interval has already started."
            )
        if _is_blocked(reservation, now, policy):
            raise TransitionRefused(
                CONFLICT, "OVERLAP", "The companion is not available for this interval."
            )

        if policy.requires_approval(reservation.companion):
            reservation.status = ReservationStatus.PENDING_APPROVAL
            reservation.approval_requested_at = now
            reservation.approval_deadline = policy.deadline_for(reservation, now)
            event = notifications.AWAITING_APPROVAL
        else:
            reservation.status = ReservationStatus.CONFIRMED
            event = notifications.CONFIRMED
        reservation.save()
        _notify_after_commit(event, reservation)
    return TransitionOutcome(reservation)


def cancel(
    reservation: Reservation,
    actor: AbstractBaseUser,
    now: datetime | None = None,
    policy: approval.ApprovalPolicy | None = None,
) -> TransitionOutcome:
    now = now or timezone.now()
    policy = policy or approval.get_policy()
    expired = False
    with transaction.atomic():
        reservation = _reload(reservation)
        allowed_actors = {reservation.customer_id, reservation.companion.user_id}
        if actor.pk not in allowed_actors:
            raise TransitionRefused(
                FORBIDDEN, "FORBIDDEN_ACTOR", "Only the customer or the booked companion can cancel."
            )
        if reservation.status == ReservationStatus.CANCELLED:
            return TransitionOutcome(reservation, idempotent=True)
        if reservation.status not in CANCELLABLE_STATES:
            raise TransitionRefused(
                CONFLICT, "INVALID_STATE", f"A {reservation.status} reservation cannot be cancelled."
            )

        if approval.effective_status(reservation, now, policy) == ReservationStatus.EXPIRED:
            reservation.status = ReservationStatus.EXPIRED
            reservation.save()
            expired = True

        elif reservation.status == ReservationStatus.CONFIRMED:
            if now > reservation.start_at - CONFIRMED_CANCEL_NOTICE:
                raise TransitionRefused(
                    CONFLICT,
                    "TOO_LATE",
                    "A confirmed reservation can only be cancelled 24 h before its start.",
                )
        elif now >= reservation.start_at:
            raise TransitionRefused(
                CONFLICT, "TOO_LATE", "The reservation interval has already started."
            )

        if not expired:
            reservation.status = ReservationStatus.CANCELLED
            reservation.save()
            _notify_after_commit(notifications.CANCELLED, reservation)

    if expired:
        raise TransitionRefused(
            CONFLICT, "EXPIRED", "The approval window closed; the reservation is no longer active."
        )
    return TransitionOutcome(reservation)


def _decide(
    reservation: Reservation,
    actor: AbstractBaseUser,
    target_status: str,
    now: datetime | None = None,
    policy: approval.ApprovalPolicy | None = None,
) -> TransitionOutcome:
    now = now or timezone.now()
    policy = policy or approval.get_policy()
    expired = False
    with transaction.atomic():
        reservation = _reload(reservation)
        if reservation.companion.user_id != actor.pk:
            raise TransitionRefused(
                FORBIDDEN,
                "FORBIDDEN_ACTOR",
                "Only the booked companion can decide about this request.",
            )
        if reservation.status != ReservationStatus.PENDING_APPROVAL:
            raise TransitionRefused(
                CONFLICT,
                "INVALID_STATE",
                f"Reservation is {reservation.status}, not PENDING_APPROVAL.",
            )

        if approval.effective_status(reservation, now, policy) == ReservationStatus.EXPIRED:
            reservation.status = ReservationStatus.EXPIRED
            reservation.save()
            expired = True
        else:
            if target_status == ReservationStatus.CONFIRMED and _is_blocked(
                reservation, now, policy
            ):
                raise TransitionRefused(
                    CONFLICT, "OVERLAP", "The interval is already blocked by another reservation."
                )
            reservation.status = target_status
            reservation.decided_by = actor
            reservation.save()
            _notify_after_commit(notifications.DECIDED, reservation)

    if expired:
        raise TransitionRefused(CONFLICT, "EXPIRED", "The approval window has already closed.")
    return TransitionOutcome(reservation)


def approve(
    reservation: Reservation,
    actor: AbstractBaseUser,
    now: datetime | None = None,
    policy: approval.ApprovalPolicy | None = None,
) -> TransitionOutcome:
    return _decide(reservation, actor, ReservationStatus.CONFIRMED, now, policy)


def reject(
    reservation: Reservation,
    actor: AbstractBaseUser,
    now: datetime | None = None,
    policy: approval.ApprovalPolicy | None = None,
) -> TransitionOutcome:
    return _decide(reservation, actor, ReservationStatus.REJECTED, now, policy)


def reconcile_overdue_approvals(
    now: datetime | None = None, policy: approval.ApprovalPolicy | None = None
) -> int:
    now = now or timezone.now()
    policy = policy or approval.get_policy()
    return Reservation.objects.filter(policy.overdue_q(now)).update(
        status=ReservationStatus.EXPIRED
    )
