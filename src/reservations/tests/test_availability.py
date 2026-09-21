"""OP-02 Check Availability — REQ-02, BR-01 (half-open intervals), BR-02."""

from datetime import timedelta

import pytest
from django.utils import timezone

from reservations.models import ReservationStatus


def availability(api_client, companion, start_at, end_at):
    return api_client.get(
        f"/companions/{companion.pk}/availability",
        {"start_at": start_at.isoformat(), "end_at": end_at.isoformat()},
    )


@pytest.mark.django_db
def test_free_interval_is_available(api_client, companion):
    start = timezone.now() + timedelta(days=7)

    response = availability(api_client, companion, start, start + timedelta(hours=2))

    assert response.status_code == 200
    assert response.data["available"] is True
    assert response.data["blocking_reservations"] == []


@pytest.mark.django_db
def test_confirmed_overlap_makes_interval_unavailable(api_client, companion, make_reservation):
    start = timezone.now() + timedelta(days=7)
    booked = make_reservation(companion, start_at=start, status=ReservationStatus.CONFIRMED)

    response = availability(
        api_client, companion, start + timedelta(hours=1), start + timedelta(hours=3)
    )

    assert response.data["available"] is False
    assert response.data["blocking_reservations"] == [str(booked.id)]


@pytest.mark.django_db
def test_touching_intervals_do_not_overlap(api_client, companion, make_reservation):
    start = timezone.now() + timedelta(days=7)
    make_reservation(companion, start_at=start, hours=1, status=ReservationStatus.CONFIRMED)

    before = availability(api_client, companion, start - timedelta(hours=1), start)
    after = availability(
        api_client, companion, start + timedelta(hours=1), start + timedelta(hours=2)
    )

    assert before.data["available"] is True
    assert after.data["available"] is True


@pytest.mark.django_db
def test_draft_does_not_block(api_client, companion, make_reservation):
    start = timezone.now() + timedelta(days=7)
    make_reservation(companion, start_at=start, status=ReservationStatus.DRAFT)

    response = availability(api_client, companion, start, start + timedelta(hours=2))

    assert response.data["available"] is True


@pytest.mark.django_db
def test_pending_approval_blocks_until_its_deadline(
    api_client, approval_companion, make_reservation
):
    start = timezone.now() + timedelta(days=7)
    live = make_reservation(
        approval_companion,
        start_at=start,
        status=ReservationStatus.PENDING_APPROVAL,
        approval_deadline=timezone.now() + timedelta(hours=1),
    )
    blocked = availability(api_client, approval_companion, start, start + timedelta(hours=2))

    live.approval_deadline = timezone.now() - timedelta(seconds=1)
    live.save()
    free = availability(api_client, approval_companion, start, start + timedelta(hours=2))

    assert blocked.data["available"] is False
    assert free.data["available"] is True


@pytest.mark.django_db
def test_cancelled_reservation_frees_the_interval(api_client, companion, make_reservation):
    start = timezone.now() + timedelta(days=7)
    make_reservation(companion, start_at=start, status=ReservationStatus.CANCELLED)

    response = availability(api_client, companion, start, start + timedelta(hours=2))

    assert response.data["available"] is True


@pytest.mark.django_db
def test_inactive_companion_is_not_available(api_client, companion):
    companion.is_active = False
    companion.save()
    start = timezone.now() + timedelta(days=7)

    response = availability(api_client, companion, start, start + timedelta(hours=2))

    assert response.data["available"] is False
    assert response.data["companion_active"] is False


@pytest.mark.django_db
def test_rejects_invalid_interval(api_client, companion):
    start = timezone.now() + timedelta(days=7)

    response = availability(api_client, companion, start, start)

    assert response.status_code == 400
    assert "end_at" in response.data


@pytest.mark.django_db
def test_unknown_companion_returns_404(api_client, db):
    start = timezone.now() + timedelta(days=7)

    response = api_client.get(
        "/companions/999999/availability",
        {"start_at": start.isoformat(), "end_at": (start + timedelta(hours=1)).isoformat()},
    )

    assert response.status_code == 404
