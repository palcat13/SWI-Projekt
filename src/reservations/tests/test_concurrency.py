"""REQ-04 under real parallelism — two confirmations race for the same companion (ADR-01 addendum)."""

import json
import threading
import time
import urllib.error
import urllib.request
from datetime import timedelta

import pytest
from django.utils import timezone

from reservations import lifecycle
from reservations.models import Reservation, ReservationStatus

RACE_WINDOW = 0.2  # seconds between the BR-02 probe and the write; well under SQLite's 5 s busy timeout


def post_json(url, payload):
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        body = error.read()
        try:
            return error.code, json.loads(body)
        except ValueError:  # Django's plain 500 page
            return error.code, {}


def confirm_in_parallel(base_url, reservations, actor):
    """Send one real HTTP confirm request per reservation, all released at the same moment.

    A real server, not the in-process test client: the test client hooks the process-wide
    got_request_exception signal, so one thread's 500 would be re-raised in the other thread too.
    """
    start_line = threading.Barrier(len(reservations))
    outcomes = {}

    def run(reservation):
        start_line.wait(timeout=10)
        status, body = post_json(
            f"{base_url}/reservations/{reservation.id}/confirm", {"actor_user_id": actor.pk}
        )
        outcomes[reservation.id] = (status, body.get("error"))

    threads = [threading.Thread(target=run, args=(r,)) for r in reservations]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return outcomes


@pytest.fixture
def slow_probe(monkeypatch):
    """Hold every confirmation between its BR-02 probe and its write, so the two requests overlap."""
    probe = lifecycle._is_blocked

    def held(*args, **kwargs):
        blocked = probe(*args, **kwargs)
        time.sleep(RACE_WINDOW)
        return blocked

    monkeypatch.setattr(lifecycle, "_is_blocked", held)


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "which, winner_status",
    [("companion", ReservationStatus.CONFIRMED), ("approval_companion", ReservationStatus.PENDING_APPROVAL)],
)
def test_two_racing_confirmations_end_with_exactly_one_winner(
    request, which, winner_status, live_server, customer, make_reservation, slow_probe
):
    companion = request.getfixturevalue(which)
    start = timezone.now() + timedelta(days=7)
    first = make_reservation(companion, start_at=start)
    second = make_reservation(companion, start_at=start + timedelta(hours=1))

    outcomes = confirm_in_parallel(live_server.url, [first, second], customer)

    assert sorted(outcomes.values(), key=lambda o: o[0]) == [(200, None), (409, "OVERLAP")]
    stored = sorted(Reservation.objects.filter(id__in=[first.id, second.id]).values_list("status", flat=True))
    assert stored == sorted([winner_status, ReservationStatus.DRAFT])
