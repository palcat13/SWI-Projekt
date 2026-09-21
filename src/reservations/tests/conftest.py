from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from reservations.models import Activity, Companion, Reservation, ReservationStatus


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def customer(db):
    return get_user_model().objects.create_user(username="customer", password="x")


@pytest.fixture
def other_customer(db):
    return get_user_model().objects.create_user(username="customer-2", password="x")


@pytest.fixture
def companion(db):
    user = get_user_model().objects.create_user(username="companion", password="x")
    return Companion.objects.create(user=user, display_name="Alice")


@pytest.fixture
def approval_companion(db):
    user = get_user_model().objects.create_user(username="companion-approval", password="x")
    return Companion.objects.create(user=user, display_name="Bea", requires_approval=True)


@pytest.fixture
def valid_payload(companion, customer):
    start = timezone.now() + timedelta(days=1)
    return {
        "companion_id": companion.pk,
        "customer_id": customer.pk,
        "start_at": start.isoformat(),
        "end_at": (start + timedelta(hours=2)).isoformat(),
        "activity": "DINNER",
    }


@pytest.fixture
def make_reservation(db, customer):
    def _make(companion, start_at=None, hours=2, status=ReservationStatus.DRAFT, **kwargs):
        start_at = start_at or timezone.now() + timedelta(days=7)
        kwargs.setdefault("customer", customer)
        return Reservation.objects.create(
            companion=companion,
            start_at=start_at,
            end_at=start_at + timedelta(hours=hours),
            activity=Activity.DINNER,
            status=status,
            **kwargs,
        )

    return _make
