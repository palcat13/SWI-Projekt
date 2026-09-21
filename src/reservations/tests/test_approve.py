"""OP-05 Approve / OP-06 Reject and the expiry of the approval window (baseline v0.2)."""

from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from reservations.models import Reservation, ReservationStatus


@pytest.fixture
def pending(approval_companion, make_reservation):
    return make_reservation(
        approval_companion,
        status=ReservationStatus.PENDING_APPROVAL,
        approval_requested_at=timezone.now(),
        approval_deadline=timezone.now() + timedelta(hours=1),
    )


def decide(api_client, reservation, actor, decision):
    return api_client.post(
        f"/reservations/{reservation.id}/{decision}", {"actor_user_id": actor.pk}, format="json"
    )


@pytest.mark.django_db
def test_companion_approves_pending_request(api_client, approval_companion, pending):
    response = decide(api_client, pending, approval_companion.user, "approve")

    assert response.status_code == 200
    assert response.data["status"] == ReservationStatus.CONFIRMED
    pending.refresh_from_db()
    assert pending.decided_by == approval_companion.user


@pytest.mark.django_db
def test_companion_rejects_pending_request(api_client, approval_companion, pending):
    response = decide(api_client, pending, approval_companion.user, "reject")

    assert response.data["status"] == ReservationStatus.REJECTED


@pytest.mark.django_db
def test_customer_cannot_reject_request(api_client, customer, pending):
    response = decide(api_client, pending, customer, "reject")

    assert response.status_code == 403
    assert response.data["error"] == "FORBIDDEN_ACTOR"
    pending.refresh_from_db()
    assert pending.status == ReservationStatus.PENDING_APPROVAL


@pytest.mark.django_db
def test_cannot_reject_a_draft(api_client, approval_companion, make_reservation):
    reservation = make_reservation(approval_companion)

    response = decide(api_client, reservation, approval_companion.user, "reject")

    assert response.status_code == 409
    assert response.data["error"] == "INVALID_STATE"


@pytest.mark.django_db
def test_customer_cannot_approve_own_request(api_client, customer, pending):
    response = decide(api_client, pending, customer, "approve")

    assert response.status_code == 403
    assert response.data["error"] == "FORBIDDEN_ACTOR"
    pending.refresh_from_db()
    assert pending.status == ReservationStatus.PENDING_APPROVAL


@pytest.mark.django_db
def test_approval_after_the_deadline_expires_the_request(
    api_client, approval_companion, pending
):
    pending.approval_deadline = timezone.now() - timedelta(seconds=1)
    pending.save()

    response = decide(api_client, pending, approval_companion.user, "approve")

    assert response.status_code == 409
    assert response.data["error"] == "EXPIRED"
    pending.refresh_from_db()
    assert pending.status == ReservationStatus.EXPIRED


@pytest.mark.django_db
def test_cannot_approve_a_draft(api_client, approval_companion, make_reservation):
    reservation = make_reservation(approval_companion)

    response = decide(api_client, reservation, approval_companion.user, "approve")

    assert response.status_code == 409
    assert response.data["error"] == "INVALID_STATE"


@pytest.mark.django_db
def test_approval_is_refused_when_the_slot_got_taken(
    api_client, approval_companion, pending, make_reservation
):
    make_reservation(
        approval_companion,
        start_at=pending.start_at + timedelta(hours=1),
        status=ReservationStatus.CONFIRMED,
    )

    response = decide(api_client, pending, approval_companion.user, "approve")

    assert response.status_code == 409
    assert response.data["error"] == "OVERLAP"
    pending.refresh_from_db()
    assert pending.status == ReservationStatus.PENDING_APPROVAL


@pytest.mark.django_db
def test_expiry_command_marks_only_overdue_requests(
    api_client, approval_companion, pending, make_reservation
):
    overdue = make_reservation(
        approval_companion,
        start_at=pending.start_at + timedelta(days=1),
        status=ReservationStatus.PENDING_APPROVAL,
        approval_deadline=timezone.now() - timedelta(minutes=1),
    )

    call_command("expire_pending_approvals")

    assert Reservation.objects.get(id=overdue.id).status == ReservationStatus.EXPIRED
    assert Reservation.objects.get(id=pending.id).status == ReservationStatus.PENDING_APPROVAL
