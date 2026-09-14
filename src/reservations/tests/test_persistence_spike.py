"""C01 engineering spike A: Reservation -> real DB -> load -> verify."""

from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

import pytest
from django.db import IntegrityError, transaction

from reservations.models import Reservation, ReservationStatus


@pytest.mark.django_db
def test_reservation_round_trip_through_database(companion, customer):
    start = datetime(2030, 3, 30, 18, 30, tzinfo=ZoneInfo("Europe/Prague"))
    created = Reservation.objects.create(
        companion=companion,
        customer=customer,
        start_at=start,
        end_at=start + timedelta(hours=2),
        status=ReservationStatus.PENDING_APPROVAL,
    )

    loaded = Reservation.objects.select_related("companion", "customer").get(id=created.id)

    assert loaded is not created
    assert loaded.id == created.id
    assert loaded.companion.display_name == "Alice"
    assert loaded.customer.username == "customer"
    assert loaded.status == ReservationStatus.PENDING_APPROVAL
    assert loaded.start_at == start
    assert loaded.start_at.tzinfo is not None
    assert loaded.start_at == datetime(2030, 3, 30, 17, 30, tzinfo=dt_timezone.utc)
    assert loaded.end_at - loaded.start_at == timedelta(hours=2)
    assert loaded.created_at is not None


@pytest.mark.django_db
def test_database_rejects_end_before_start(companion, customer):
    start = datetime(2030, 1, 1, 10, 0, tzinfo=dt_timezone.utc)

    with pytest.raises(IntegrityError), transaction.atomic():
        Reservation.objects.create(
            companion=companion, customer=customer, start_at=start, end_at=start
        )
