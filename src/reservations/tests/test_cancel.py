"""OP-04 Cancel Reservation — REQ-05, BR-03 (24 h notice for CONFIRMED)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from reservations.models import ReservationStatus


def cancel(api_client, reservation, actor):
    return api_client.post(
        f"/reservations/{reservation.id}/cancel", {"actor_user_id": actor.pk}, format="json"
    )


@pytest.mark.django_db
def test_customer_cancels_draft(api_client, companion, customer, make_reservation):
    reservation = make_reservation(companion)

    response = cancel(api_client, reservation, customer)

    assert response.status_code == 200
    assert response.data["status"] == ReservationStatus.CANCELLED


@pytest.mark.django_db
def test_companion_may_cancel(api_client, companion, make_reservation):
    reservation = make_reservation(companion, status=ReservationStatus.CONFIRMED)

    response = cancel(api_client, reservation, companion.user)

    assert response.data["status"] == ReservationStatus.CANCELLED


@pytest.mark.django_db
def test_cancelling_confirmed_frees_the_interval(
    api_client, companion, customer, make_reservation
):
    start = timezone.now() + timedelta(days=7)
    reservation = make_reservation(companion, start_at=start, status=ReservationStatus.CONFIRMED)

    cancel(api_client, reservation, customer)
    availability = api_client.get(
        f"/companions/{companion.pk}/availability",
        {"start_at": start.isoformat(), "end_at": (start + timedelta(hours=2)).isoformat()},
    )

    assert availability.data["available"] is True


@pytest.mark.django_db
def test_confirmed_just_outside_the_notice_window_can_be_cancelled(
    api_client, companion, customer, make_reservation
):
    start = timezone.now() + timedelta(hours=24, minutes=1)
    reservation = make_reservation(companion, start_at=start, status=ReservationStatus.CONFIRMED)

    response = cancel(api_client, reservation, customer)

    assert response.data["status"] == ReservationStatus.CANCELLED


@pytest.mark.django_db
def test_confirmed_inside_the_notice_window_is_rejected(
    api_client, companion, customer, make_reservation
):
    start = timezone.now() + timedelta(hours=23, minutes=59)
    reservation = make_reservation(companion, start_at=start, status=ReservationStatus.CONFIRMED)

    response = cancel(api_client, reservation, customer)

    assert response.status_code == 409
    assert response.data["error"] == "TOO_LATE"
    reservation.refresh_from_db()
    assert reservation.status == ReservationStatus.CONFIRMED


@pytest.mark.django_db
def test_draft_can_be_cancelled_up_to_the_start(api_client, companion, customer, make_reservation):
    late_draft = make_reservation(companion, start_at=timezone.now() + timedelta(minutes=5))
    started_draft = make_reservation(companion, start_at=timezone.now() - timedelta(minutes=5))

    assert cancel(api_client, late_draft, customer).data["status"] == ReservationStatus.CANCELLED
    started = cancel(api_client, started_draft, customer)
    assert started.status_code == 409
    assert started.data["error"] == "TOO_LATE"


@pytest.mark.django_db
def test_pending_approval_can_be_cancelled(
    api_client, approval_companion, customer, make_reservation
):
    reservation = make_reservation(
        approval_companion,
        status=ReservationStatus.PENDING_APPROVAL,
        approval_deadline=timezone.now() + timedelta(hours=1),
    )

    response = cancel(api_client, reservation, customer)

    assert response.data["status"] == ReservationStatus.CANCELLED


@pytest.mark.django_db
def test_second_cancel_is_idempotent(api_client, companion, customer, make_reservation):
    reservation = make_reservation(companion, status=ReservationStatus.CANCELLED)

    response = cancel(api_client, reservation, customer)

    assert response.status_code == 200
    assert response.data["idempotent"] is True


@pytest.mark.django_db
def test_rejected_reservation_cannot_be_cancelled(
    api_client, approval_companion, customer, make_reservation
):
    reservation = make_reservation(approval_companion, status=ReservationStatus.REJECTED)

    response = cancel(api_client, reservation, customer)

    assert response.status_code == 409
    assert response.data["error"] == "INVALID_STATE"


@pytest.mark.django_db
def test_stranger_cannot_cancel(api_client, companion, other_customer, make_reservation):
    reservation = make_reservation(companion)

    response = cancel(api_client, reservation, other_customer)

    assert response.status_code == 403
    assert response.data["error"] == "FORBIDDEN_ACTOR"
