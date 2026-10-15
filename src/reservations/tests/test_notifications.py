"""DR-3 — the notification boundary: dispatch happens after commit and cannot undo the state."""

import pytest

from reservations import lifecycle, notifications
from reservations.models import ReservationStatus


class RecordingPort(notifications.NotificationPort):
    def __init__(self):
        self.events = []

    def notify(self, event, reservation):
        self.events.append((event, reservation.id))


class FailingPort(notifications.NotificationPort):
    def notify(self, event, reservation):
        raise RuntimeError("the notification service is down")


@pytest.fixture
def recording_port():
    port = RecordingPort()
    previous = notifications.set_port(port)
    yield port
    notifications.set_port(previous)


@pytest.fixture
def failing_port():
    previous = notifications.set_port(FailingPort())
    yield
    notifications.set_port(previous)


@pytest.mark.django_db
def test_confirmation_notifies_only_after_the_transaction_commits(
    companion, customer, make_reservation, recording_port, django_capture_on_commit_callbacks
):
    reservation = make_reservation(companion)

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        lifecycle.confirm(reservation, customer)
        assert recording_port.events == []

    assert len(callbacks) == 1
    callbacks[0]()
    assert recording_port.events == [(notifications.CONFIRMED, reservation.id)]


@pytest.mark.django_db
def test_a_failing_notification_does_not_undo_the_committed_state(
    companion, customer, make_reservation, failing_port, django_capture_on_commit_callbacks
):
    reservation = make_reservation(companion)

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        lifecycle.confirm(reservation, customer)

    reservation.refresh_from_db()
    assert reservation.status == ReservationStatus.CONFIRMED

    with pytest.raises(RuntimeError):
        callbacks[0]()

    reservation.refresh_from_db()
    assert reservation.status == ReservationStatus.CONFIRMED


@pytest.mark.django_db
def test_a_request_awaiting_approval_notifies_with_its_own_event(
    approval_companion, customer, make_reservation, recording_port, django_capture_on_commit_callbacks
):
    reservation = make_reservation(approval_companion)

    with django_capture_on_commit_callbacks(execute=True):
        lifecycle.confirm(reservation, customer)

    assert recording_port.events == [(notifications.AWAITING_APPROVAL, reservation.id)]
