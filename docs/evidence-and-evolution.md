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
- Re-run by the second team member on their own checkout after PR #2 (2026-09-14, Python 3.10.12): **14 passed** (12 CP1 tests including the `activity` validation + 2 spike tests); `manage.py check` reports no issues and `makemigrations --check` detects no missing migrations.
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
- **Open (for the future pressure):** SQLite does not support row locking (`select_for_update`). The rule "confirmed reservations must not overlap" under concurrent confirmations is not verified yet. This is a future scaling concern outside our selected C pressure; moving to PostgreSQL would address it (see D3).
- **Review:** the spike change (PR #1) was reviewed and approved by the second team member before merging; the tests were re-run on their checkout (see *Observed result*).

---

# Evidence C02: specification → running application

## Accepted baseline
- **v0.1** — approved by the team on 2026-09-21: OP-01 Create, OP-02 Check Availability, OP-03 Confirm (direct `DRAFT → CONFIRMED`), OP-04 Cancel, rules BR-01 … BR-06. See [specification.md](specification.md).
- **v0.2** — after change C02 (approval process): OP-05 Approve, OP-06 Reject, states `PENDING_APPROVAL`, `REJECTED`, `EXPIRED`, amended BR-02 (a live pending request blocks) and BR-04 (the C01 rule back in force for companions with `requires_approval`).

## Demonstrated core operations
A Django + DRF application (`src/`), a REST interface without a UI. All operations of baseline v0.2 are runnable: `POST /reservations`, `GET /companions/{id}/availability`, and `POST /reservations/{uuid}/confirm|cancel|approve|reject`, plus the `expire_pending_approvals` command.

## Verification examples actually run
**Automated:** `pytest` → **50 passed** at the time of PR #3 (2026-09-21, Python 3.12.3, Django 5.2.17, DRF 3.18.1). During the team review the second member added the two OP-06 examples that the specification lists but nobody had run, and re-ran the suite on their own checkout (Python 3.10.12): **52 passed**. Per operation: `test_availability.py` (9), `test_confirm.py` (10), `test_cancel.py` (10), `test_approve.py` (9, OP-05 + OP-06 + expiry), plus the CP1 create tests and the C01 persistence spike. Boundaries covered: touching intervals `[10,11)` / `[11,12)`, cancellation 23 h 59 min vs. 24 h 01 min before the start, approval 1 s after the deadline, a pending request before and after its deadline, two conflicting confirmations in sequence.

**Manual through a running server** — `scripts/demo_c02.sh` (reproducible, migrates + seeds + starts the server on port 8765). Verbatim output of the run from 2026-09-21 after the review, one successful and one negative example per operation:

```
===== OP-01 Create Reservation =====

--- success: new DRAFT
{"id":"13b7a891-cf9a-4623-ac3a-3bc773d51d9c","status":"DRAFT"}
HTTP 201

--- negative: end_at before start_at
{"end_at":["end_at must be after start_at."]}
HTTP 400
===== OP-02 Check Availability =====

--- success: free slot (only DRAFTs so far)
{"companion_id":1,"start_at":"2026-09-28T16:18:14.500033Z","end_at":"2026-09-28T18:18:14.500033Z","available":true,"companion_active":true,"blocking_reservations":[]}
HTTP 200

--- negative: invalid interval
{"end_at":["end_at must be after start_at."]}
HTTP 400
===== OP-03 Confirm Reservation =====

--- success: DRAFT -> CONFIRMED
{"id":"d293a60d-5983-4f87-906c-4b74220f6ed8","status":"CONFIRMED","approval_deadline":null}
HTTP 200

--- boundary: the slot is now unavailable
{"companion_id":1,"start_at":"2026-09-28T16:18:14.500033Z","end_at":"2026-09-28T18:18:14.500033Z","available":false,"companion_active":true,"blocking_reservations":["d293a60d-5983-4f87-906c-4b74220f6ed8"]}
HTTP 200

--- negative: overlapping confirmation
{"error":"OVERLAP","detail":"The companion is not available for this interval."}
HTTP 409
===== OP-04 Cancel Reservation =====

--- success: CONFIRMED cancelled 7 days ahead
{"id":"d293a60d-5983-4f87-906c-4b74220f6ed8","status":"CANCELLED","approval_deadline":null}
HTTP 200

--- negative: CONFIRMED within the 24 h notice (starts in 12 h)
{"error":"TOO_LATE","detail":"A confirmed reservation can only be cancelled 24 h before its start."}
HTTP 409
===== OP-05 / OP-06 Approve and Reject (v0.2) =====

--- success: confirmation of an approval-requiring companion -> PENDING_APPROVAL
{"id":"1e7dfb80-41c6-4668-b85d-532b8a46f031","status":"PENDING_APPROVAL","approval_deadline":"2026-09-22T16:18:15.343002Z"}
HTTP 200

--- negative: the customer cannot approve their own request
{"error":"FORBIDDEN_ACTOR","detail":"Only the booked companion can decide about this request."}
HTTP 403

--- success: the booked companion approves
{"id":"1e7dfb80-41c6-4668-b85d-532b8a46f031","status":"CONFIRMED","approval_deadline":"2026-09-22T16:18:15.343002Z"}
HTTP 200

--- negative: the customer cannot reject the request
{"error":"FORBIDDEN_ACTOR","detail":"Only the booked companion can decide about this request."}
HTTP 403

--- success: the booked companion rejects another request
{"id":"dd42c545-4439-4c86-a5db-30ec247308db","status":"REJECTED","approval_deadline":"2026-09-21T17:18:14.663836Z"}
HTTP 200
===== expiry of the approval window =====

--- expire_pending_approvals (one request past its deadline)
expired=1
```

## Found inconsistencies and how they were resolved
1. **C01 domain rule vs. the C02 baseline.** The C01 Project Frame required approval of *every* reservation, but C02 forbids `Approve` in baseline v0.1. **Resolution:** the source at fault was the scope of the rule, not the code. BR-04 is deliberately relaxed in v0.1 (direct confirmation) and change C02 brings it back for companions with `requires_approval = true`. Both documents now say so explicitly, and the C01 state table was rewritten into the v0.2 transitions.
2. **The verification example was wrong, not the implementation.** The first demo run returned `400 "Datetime has wrong format"` for availability. The cause was the example: the `+02:00` offset in the URL query decodes as a space. The API was right; we fixed the script (`curl --data-urlencode`) and the README now says the query must be URL-encoded.
3. **Two sources of truth about expiry.** Marking `EXPIRED` by a command alone would mean that availability lies until somebody runs it. **Resolution:** the deadline is data and every availability/overlap query respects it (D9); the command only materialises the state. The residual duality is recorded as a driver for C03.

4. **A specified example that nobody ran.** OP-06 Reject listed three verification examples, but only the successful one existed as a test and the demo script did not exercise `reject` at all. **Resolution:** the source at fault was neither the specification nor the implementation — the coverage was. Both negative examples (`403` for the customer, `409 INVALID_STATE` for a `DRAFT`) were added as tests and to the demo script, and both passed against unchanged application code. OP-06 was also missing *Referenced rules* and a *Main success scenario*, which the operation template requires; they were added.

5. **The approval record did not match how the work actually happened.** The specification stated that the team had approved v0.1 and that the change was applied only afterwards, but both baselines were written in one session and merged in a single commit (PR #3), so nothing in the repository backs that sequence. **Resolution:** the source at fault was the record, not the process. The approval section now names who wrote and approved v0.1, states that the change analysis followed in the same session, and dates the second member's review separately.

## Change impact summary
Create (REQ-01), the cancellation boundary (REQ-05), idempotency (REQ-06), BR-01 and BR-05 are **unchanged**. What changed: BR-02 (the set of blocking states), BR-04 (back in force), OP-03 (splits into a request and a decision), the result of OP-02 (a consequence of BR-02), BR-03 (extended by `PENDING_APPROVAL`), plus three new states and two new operations for an actor that already existed (the Companion). Details in *C02 change impact* in [specification.md](specification.md).

## Remaining assumptions / unknowns
- The **24 h** approval window and the **24 h** cancellation notice are team-chosen values derived from the C01 assumption; they have no external source.
- **REQ-04 / REQ-09 under real parallelism** are verified only sequentially — SQLite cannot lock rows (D3).
- **Actor identity** (`actor_user_id` in the body, D7) is a stand-in for authentication.
- The **Notification Service** is still only a boundary in the specification; nothing calls it yet.

## Architectural drivers carried into C03
1. Concurrency around BR-02 → PostgreSQL with `select_for_update` or a DB exclusion constraint.
2. A time-driven process for expiry (a scheduler vs. read-time evaluation, D9).
3. The notification boundary — an interface, a stub, and a failure policy that does not roll back the state.
4. The domain rules living in `views.py` and the actor rules repeated in four views → extract a domain layer (one transition = one function).
5. Real authentication instead of `actor_user_id` (D7).

## Commit / tag
Baseline v0.2 was merged to `main` in PR #3, merge commit `e0f3ced`. The corrections from the team review (the OP-06 examples, the two activity diagrams, this evidence) follow in the review commit on top of it. The state of the application for CP1 is marked by the annotated tag **`v0.2`** — `git tag -l v0.2` on `main` must list it; if it does not, the tag was never pushed and this line is the place to notice it.
