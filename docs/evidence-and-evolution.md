# C01 Engineering Spike

Variant: **A — Persistence** (Reservation → real DB → load → verify)

## Question / unknown
Does a `Reservation` survive a round trip through a real database (SQLite) via the Django ORM and migrations with every attribute intact? In particular: the UUID identity, the status enum, and timezone-aware start/end times (customers enter local time, e.g. `Europe/Prague`). Can the database itself reject an invalid time interval?

## What we did
1. Set up the Django project and the `reservations` app with models `Companion` and `Reservation` (UUID PK, `status` TextChoices, `start_at`/`end_at`, check constraint `start_at < end_at`); settings `USE_TZ = True`, `TIME_ZONE = "UTC"`.
2. `python manage.py makemigrations reservations` → `0001_initial.py`; `python manage.py migrate` against the file DB `src/db.sqlite3`.
3. Automated test `src/reservations/tests/test_persistence_spike.py`:
   - creates a reservation with `start_at = 2030-03-30 18:30 Europe/Prague`, status `PENDING_APPROVAL`, loads it back with a fresh query (`Reservation.objects.get(id=...)`) and compares id, companion, customer, status, times (incl. the conversion to UTC) and `created_at`;
   - tries to save a reservation with `start_at == end_at` and expects an `IntegrityError` from the database.
4. Manual end-to-end check against the persistent file DB (not the test DB):
   ```bash
   cd src
   python manage.py shell -c "...create demo-customer, demo-companion, Companion 'Alice'..."
   python manage.py runserver 127.0.0.1:8765
   curl -X POST 127.0.0.1:8765/reservations -H 'Content-Type: application/json' \
     -d '{"companion_id":1,"customer_id":1,"start_at":"2026-10-01T18:00:00+02:00","end_at":"2026-10-01T20:00:00+02:00"}'
   curl -X POST ... -d '{... "start_at":"2026-10-01T20:00:00Z","end_at":"2026-10-01T18:00:00Z"}'
   # stop the server, then in a new process:
   python manage.py shell -c "from reservations.models import Reservation; r = Reservation.objects.get(id='<id>'); print(r.id, r.companion, r.customer, r.start_at, r.end_at, r.status)"
   ```

## Observed result
- `pytest` (2026-09-14, Python 3.12.3, Django 5.2.17, DRF 3.18.1): **12 passed** (10 CP1 tests + 2 spike tests).
- **The first run of the spike test failed:** the test expected `18:30 Europe/Prague` = `16:30 UTC`, but the DB returned `17:30 UTC`. The database was right. 30 March 2030 is still winter time (CET, UTC+1); the switch to summer time happens on 31 March. The test's expectation was wrong, not the persistence. After fixing the expectation the test passes.
- The DB rejected a reservation with `start_at == end_at` via `IntegrityError` (check constraint `reservation_start_before_end`).
- Manual check:
  ```
  POST valid   → HTTP 201 {"id":"971a6fb1-0ed0-4af0-95ef-d00acd839877","status":"DRAFT"}
  POST invalid → HTTP 400 {"end_at":["end_at must be after start_at."]}
  read back (new process):
  971a6fb1-0ed0-4af0-95ef-d00acd839877 Alice demo-customer 2026-10-01 16:00:00+00:00 2026-10-01 18:00:00+00:00 DRAFT
  ```
  A time sent as `+02:00` is stored and returned normalised to UTC; the row survives a server restart.

## Decision / what changes because of the result
- **Keep SQLite + Django ORM** for CP1 and the next steps; persistence of all Reservation attributes is verified.
- **Times are always stored and compared in UTC** (`USE_TZ = True`). The API accepts ISO-8601 with an offset; conversion to local time is only a presentation concern. The overlap rule will therefore compare UTC intervals, and around DST changes it will behave correctly.
- **Tests with local times must not assume a fixed offset.** Expected values are written directly in UTC (a lesson from the failed first run).
- **The `start_at < end_at` invariant is enforced twice:** in the serializer (a friendly `400`) and as a DB constraint (a safety net against bypassing the API).
- **Open (for the future pressure):** SQLite does not support row locking (`select_for_update`). The rule "confirmed reservations must not overlap" under concurrent confirmations is not verified yet. This is a candidate for the Q pressure and for moving to PostgreSQL (see D3).
- **Still to do for the C01 DoD:** a second team member reviews this change and re-runs `pytest` + the manual check from the README on a clean checkout.
