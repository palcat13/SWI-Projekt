"""OP-03 Confirm Reservation — REQ-03, REQ-04, BR-02, BR-04 (approval in v0.2)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from reservations.models import ReservationStatus


def confirm(api_client, reservation, actor):
    return api_client.post(
        f"/reservations/{reservation.id}/confirm", {"actor_user_id": actor.pk}, format="json"
    )


@pytest.mark.django_db
def test_customer_confirms_draft(api_client, companion, customer, make_reservation):
    reservation = make_reservation(companion)

    response = confirm(api_client, reservation, customer)

    assert response.status_code == 200
    assert response.data["status"] == ReservationStatus.CONFIRMED
    reservation.refresh_from_db()
    assert reservation.status == ReservationStatus.CONFIRMED
    assert reservation.approval_deadline is None


@pytest.mark.django_db
def test_companion_requiring_approval_goes_to_pending(
    api_client, approval_companion, customer, make_reservation
):
    reservation = make_reservation(approval_companion)

    response = confirm(api_client, reservation, customer)

    assert response.data["status"] == ReservationStatus.PENDING_APPROVAL
    reservation.refresh_from_db()
    assert reservation.approval_requested_at is not None
    assert reservation.approval_deadline <= reservation.approval_requested_at + timedelta(hours=24)


@pytest.mark.django_db
def test_approval_deadline_never_exceeds_the_start(
    api_client, approval_companion, customer, make_reservation
):
    start = timezone.now() + timedelta(hours=3)
    reservation = make_reservation(approval_companion, start_at=start)

    confirm(api_client, reservation, customer)

    reservation.refresh_from_db()
    assert reservation.approval_deadline == reservation.start_at


@pytest.mark.django_db
def test_rejects_wrong_actor(api_client, companion, other_customer, make_reservation):
    reservation = make_reservation(companion)

    response = confirm(api_client, reservation, other_customer)

    assert response.status_code == 403
    assert response.data["error"] == "FORBIDDEN_ACTOR"
    reservation.refresh_from_db()
    assert reservation.status == ReservationStatus.DRAFT


@pytest.mark.django_db
def test_rejects_non_draft_state(api_client, companion, customer, make_reservation):
    reservation = make_reservation(companion, status=ReservationStatus.CONFIRMED)

    response = confirm(api_client, reservation, customer)

    assert response.status_code == 409
    assert response.data["error"] == "INVALID_STATE"


@pytest.mark.django_db
def test_rejects_overlap_with_confirmed(api_client, companion, customer, make_reservation):
    start = timezone.now() + timedelta(days=7)
    make_reservation(companion, start_at=start, status=ReservationStatus.CONFIRMED)
    reservation = make_reservation(companion, start_at=start + timedelta(hours=1))

    response = confirm(api_client, reservation, customer)

    assert response.status_code == 409
    assert response.data["error"] == "OVERLAP"
    reservation.refresh_from_db()
    assert reservation.status == ReservationStatus.DRAFT


@pytest.mark.django_db
def test_only_one_of_two_conflicting_confirmations_wins(
    api_client, companion, customer, make_reservation
):
    start = timezone.now() + timedelta(days=7)
    first = make_reservation(companion, start_at=start)
    second = make_reservation(companion, start_at=start + timedelta(hours=1))

    first_response = confirm(api_client, first, customer)
    second_response = confirm(api_client, second, customer)

    assert first_response.data["status"] == ReservationStatus.CONFIRMED
    assert second_response.status_code == 409
    assert second_response.data["error"] == "OVERLAP"


@pytest.mark.django_db
def test_touching_intervals_can_both_be_confirmed(
    api_client, companion, customer, make_reservation
):
    start = timezone.now() + timedelta(days=7)
    first = make_reservation(companion, start_at=start, hours=1)
    second = make_reservation(companion, start_at=start + timedelta(hours=1), hours=1)

    assert confirm(api_client, first, customer).data["status"] == ReservationStatus.CONFIRMED
    assert confirm(api_client, second, customer).data["status"] == ReservationStatus.CONFIRMED


@pytest.mark.django_db
def test_rejects_inactive_companion(api_client, companion, customer, make_reservation):
    reservation = make_reservation(companion)
    companion.is_active = False
    companion.save()

    response = confirm(api_client, reservation, customer)

    assert response.status_code == 409
    assert response.data["error"] == "INACTIVE_RESOURCE"


@pytest.mark.django_db
def test_rejects_started_interval(api_client, companion, customer, make_reservation):
    reservation = make_reservation(companion, start_at=timezone.now() - timedelta(hours=1))

    response = confirm(api_client, reservation, customer)

    assert response.status_code == 409
    assert response.data["error"] == "PAST_INTERVAL"
