import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from reservations.models import Reservation, ReservationStatus

URL = "/reservations"


@pytest.mark.django_db
def test_create_reservation_persists_and_returns_id(api_client, valid_payload, companion, customer):
    response = api_client.post(URL, valid_payload, format="json")

    assert response.status_code == 201
    reservation_id = uuid.UUID(response.data["id"])
    assert response.data["status"] == ReservationStatus.DRAFT

    stored = Reservation.objects.get(id=reservation_id)
    assert stored.companion == companion
    assert stored.customer == customer
    assert stored.status == ReservationStatus.DRAFT


@pytest.mark.django_db
def test_rejects_end_before_start(api_client, valid_payload):
    valid_payload["end_at"] = valid_payload["start_at"]

    response = api_client.post(URL, valid_payload, format="json")

    assert response.status_code == 400
    assert "end_at" in response.data
    assert Reservation.objects.count() == 0


@pytest.mark.django_db
def test_rejects_start_in_past(api_client, valid_payload):
    start = timezone.now() - timedelta(hours=1)
    valid_payload["start_at"] = start.isoformat()
    valid_payload["end_at"] = (start + timedelta(hours=2)).isoformat()

    response = api_client.post(URL, valid_payload, format="json")

    assert response.status_code == 400
    assert "start_at" in response.data


@pytest.mark.django_db
def test_rejects_unknown_companion(api_client, valid_payload):
    valid_payload["companion_id"] = 999999

    response = api_client.post(URL, valid_payload, format="json")

    assert response.status_code == 400
    assert "companion_id" in response.data


@pytest.mark.django_db
def test_rejects_inactive_companion(api_client, valid_payload, companion):
    companion.is_active = False
    companion.save()

    response = api_client.post(URL, valid_payload, format="json")

    assert response.status_code == 400
    assert "companion_id" in response.data


@pytest.mark.django_db
def test_rejects_companion_booking_themselves(api_client, valid_payload, companion):
    valid_payload["customer_id"] = companion.user_id

    response = api_client.post(URL, valid_payload, format="json")

    assert response.status_code == 400
    assert "customer_id" in response.data


@pytest.mark.django_db
@pytest.mark.parametrize("missing", ["companion_id", "customer_id", "start_at", "end_at"])
def test_rejects_missing_field(api_client, valid_payload, missing):
    del valid_payload[missing]

    response = api_client.post(URL, valid_payload, format="json")

    assert response.status_code == 400
    assert missing in response.data
