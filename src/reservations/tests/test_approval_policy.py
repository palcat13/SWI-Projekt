"""C05 DD — tests derived from the Approval handling detailed design (T-1 ... T-9)."""

from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from reservations import approval, availability, lifecycle
from reservations.approval import FixedWindowApprovalPolicy
from reservations.models import Reservation, ReservationStatus

POLICY = FixedWindowApprovalPolicy()


def pending_stub(deadline):
    return SimpleNamespace(status=ReservationStatus.PENDING_APPROVAL, approval_deadline=deadline)


def test_t1_deadline_never_leaves_the_contract_window():
    now = timezone.now()
    for hours in (3, 25, 24 * 30):
        reservation = SimpleNamespace(start_at=now + timedelta(hours=hours))

        deadline = POLICY.deadline_for(reservation, now)

        assert now < deadline <= reservation.start_at


def test_t2_both_branches_of_the_deadline_algorithm():
    now = timezone.now()
    far = SimpleNamespace(start_at=now + timedelta(hours=30))
    near = SimpleNamespace(start_at=now + timedelta(hours=3))

    assert POLICY.deadline_for(far, now) == now + approval.DEFAULT_WINDOW
    assert POLICY.deadline_for(near, now) == near.start_at


@pytest.mark.django_db
def test_t3_in_memory_and_sql_representations_of_the_rule_agree(
    companion, approval_companion, make_reservation
):
    now = timezone.now()
    rows = [
        make_reservation(approval_companion, approval_deadline=now + timedelta(hours=1),
                         status=ReservationStatus.PENDING_APPROVAL),
        make_reservation(approval_companion, approval_deadline=now - timedelta(hours=1),
                         status=ReservationStatus.PENDING_APPROVAL),
        make_reservation(approval_companion, approval_deadline=None,
                         status=ReservationStatus.PENDING_APPROVAL),
        make_reservation(companion, status=ReservationStatus.CONFIRMED),
        make_reservation(companion, status=ReservationStatus.DRAFT),
    ]
    live_ids = set(Reservation.objects.filter(POLICY.live_q(now)).values_list("id", flat=True))

    for row in rows:
        assert POLICY.is_live(row, now) == (row.id in live_ids), row.status


@pytest.mark.django_db
def test_t4_live_and_overdue_partition_every_pending_request(approval_companion, make_reservation):
    now = timezone.now()
    for deadline in (now + timedelta(hours=1), now - timedelta(hours=1), None):
        make_reservation(approval_companion, approval_deadline=deadline,
                         status=ReservationStatus.PENDING_APPROVAL)

    pending = set(
        Reservation.objects.filter(status=ReservationStatus.PENDING_APPROVAL)
        .values_list("id", flat=True)
    )
    live = set(Reservation.objects.filter(POLICY.live_q(now)).values_list("id", flat=True))
    overdue = set(Reservation.objects.filter(POLICY.overdue_q(now)).values_list("id", flat=True))

    assert live | overdue == pending
    assert live & overdue == set()


@pytest.mark.django_db
def test_t5_reconciliation_materialises_only_overdue_rows_and_is_idempotent(
    approval_companion, make_reservation
):
    now = timezone.now()
    live = make_reservation(approval_companion, approval_deadline=now + timedelta(hours=1),
                            status=ReservationStatus.PENDING_APPROVAL)
    overdue = make_reservation(approval_companion, approval_deadline=now - timedelta(hours=1),
                               status=ReservationStatus.PENDING_APPROVAL)

    assert lifecycle.reconcile_overdue_approvals() == 1
    assert lifecycle.reconcile_overdue_approvals() == 0

    assert Reservation.objects.get(id=overdue.id).status == ReservationStatus.EXPIRED
    assert Reservation.objects.get(id=live.id).status == ReservationStatus.PENDING_APPROVAL


@pytest.mark.django_db
def test_t6_reconciliation_does_not_change_what_the_system_means(
    approval_companion, make_reservation
):
    now = timezone.now()
    overdue = make_reservation(approval_companion, approval_deadline=now - timedelta(hours=1),
                               status=ReservationStatus.PENDING_APPROVAL)

    before = availability.is_available(approval_companion, overdue.start_at, overdue.end_at)
    lifecycle.reconcile_overdue_approvals()
    after = availability.is_available(approval_companion, overdue.start_at, overdue.end_at)

    assert before is True
    assert after == before


def test_t7_a_pending_request_without_a_deadline_is_defined_not_a_crash():
    now = timezone.now()

    assert POLICY.is_live(pending_stub(None), now) is False
    assert approval.effective_status(pending_stub(None), now, POLICY) == ReservationStatus.EXPIRED


@pytest.mark.django_db
def test_t7b_approving_a_request_without_a_deadline_refuses_instead_of_raising(
    approval_companion, make_reservation
):
    reservation = make_reservation(approval_companion, approval_deadline=None,
                                   status=ReservationStatus.PENDING_APPROVAL)

    with pytest.raises(lifecycle.TransitionRefused) as refused:
        lifecycle.approve(reservation, approval_companion.user)

    assert refused.value.code == "EXPIRED"
    assert Reservation.objects.get(id=reservation.id).status == ReservationStatus.EXPIRED


@pytest.mark.django_db
def test_t8_an_effectively_expired_reservation_cannot_be_cancelled(
    approval_companion, customer, make_reservation
):
    reservation = make_reservation(
        approval_companion,
        status=ReservationStatus.PENDING_APPROVAL,
        approval_deadline=timezone.now() - timedelta(hours=1),
    )

    with pytest.raises(lifecycle.TransitionRefused) as refused:
        lifecycle.cancel(reservation, customer)

    assert refused.value.code == "EXPIRED"
    assert Reservation.objects.get(id=reservation.id).status == ReservationStatus.EXPIRED


@pytest.mark.django_db
def test_t9_the_window_is_a_variation_point(approval_companion, customer, make_reservation):
    now = timezone.now()
    short = FixedWindowApprovalPolicy(window=timedelta(hours=2))
    reservation = make_reservation(approval_companion)

    outcome = lifecycle.confirm(reservation, customer, now=now, policy=short)

    assert outcome.reservation.status == ReservationStatus.PENDING_APPROVAL
    assert outcome.reservation.approval_deadline == now + timedelta(hours=2)
    assert POLICY.deadline_for(reservation, now) == now + timedelta(hours=24)

    # ... and nothing else: the other four operations answer alike under both policies.
    pending = Reservation.objects.get(id=reservation.id)
    later = now + timedelta(hours=1)
    for policy in (short, POLICY):
        assert policy.requires_approval(approval_companion) is True
        assert policy.is_live(pending, later) is True
        assert Reservation.objects.filter(policy.live_q(later)).count() == 1
        assert Reservation.objects.filter(policy.overdue_q(later)).count() == 0
