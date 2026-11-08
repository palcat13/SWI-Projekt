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

> **Correction (review 2026-10-21):** "SQLite cannot lock rows" is true, but it locks the whole file, so
> two writers never overlap and no double booking was possible — the loser failed with `database is
> locked` (`500`) while the winner got `200`. REQ-04 is now guaranteed on SQLite with `transaction_mode = "IMMEDIATE"` and verified in
> parallel (see *C03/C05 review fixes* below); PostgreSQL is not required for it. REQ-09's re-check of
> BR-02 at approval runs in the same kind of transaction, but has no parallel test of its own.

## Commit / tag
Baseline v0.2 was merged to `main` in PR #3, merge commit `e0f3ced`. The corrections from the team review (the OP-06 examples, the two activity diagrams, this evidence) follow in the review commit on top of it. The state of the application for CP1 is marked by the annotated tag **`v0.2`** — `git tag -l v0.2` on `main` must list it; if it does not, the tag was never pushed and this line is the place to notice it.

---

# C03 — Architecture Evidence

**Baseline:** v0.2 (tag `v0.2`, commit `f764c83`) — unchanged by C03. No requirement, rule or diagram of
the specification was altered; C03 changed structure, not behaviour.

**Part A:** the AS-IS mapping of OP-03 Confirm Reservation, in
[architecture-and-decisions.md](architecture-and-decisions.md#c03-part-a--as-is-mapping-of-one-scenario).
Its central findings — the BR-02 probe and the `UPDATE` as two unlocked statements, three views reacting
to one rule, and no code at all behind the Notification Service — are the evidence behind drivers DR-1,
DR-4 and DR-3.

**Drivers:** five, in section B. DR-1 BR-02 under concurrency · DR-2 approval state outliving its
request · DR-3 the notification boundary · DR-4 one owner per lifecycle transition · DR-5 the actor's
identity. The raw C02 list earlier in the same file is marked as superseded by B, so the document has
one driver list, not two.

**Decision question:** where must the authoritative confirmation decision be made and owned, and what
enforces BR-02 when two confirmations race?

**Alternatives:** **A** — an application-layer lifecycle element owns `Reservation.status` and checks
BR-02 inside the writing transaction. **B** — PostgreSQL enforces BR-02 with an `ExclusionConstraint`
over the companion and the time range, and the application translates the `IntegrityError`.

**Scenario walkthrough:** both alternatives were walked through Confirm Reservation for a companion
requiring approval, with a concurrent conflicting confirmation and a later approval (section E3). They
differ in exactly one row — the concurrent confirmation — and the comparison in E2 showed that B buys
that row only for the `CONFIRMED` half of BR-02, because a constraint condition must be immutable and
the pending half depends on `now()`.

**ADR:** ADR-01 chooses **Alternative A** and keeps SQLite. Accepted negative consequences, recorded
rather than hidden: REQ-04 stays unguaranteed under true concurrency *(resolved 2026-10-21 by the ADR-01
addendum, see* C03/C05 review fixes*)*; nothing outside the application
protects BR-02; persistence is not substitutable; one more indirection per operation. Four explicit
reconsider-when triggers, the first being more than one concurrent user. ADR-01 supersedes the Postgres
remark in D3.

**Views:** domain class model (C1) · system context (G1) · TO-BE static architecture (G2) · state
ownership of all nine v0.2 transitions (G3) · runtime/deployment, two processes over one SQLite file
(G4) · design sequence for Confirm with an `alt` branch (H1) · focused design class diagram (H2). All
eight Mermaid diagrams were rendered with `mmdc` to confirm they parse.

**Cross-view issues found and resolved** (section I, performed on the design before any code changed):
1. `[initial] → DRAFT` had no deciding element. Creation assigns no status — the field default does.
   G3 now states this and scopes the ownership claim to transitions *between* states, which is also why
   `ReservationCreateSerializer` does not break the L2 rule.
2. The file already carried a driver list from C02. Two lists in one document is the defect this
   project hit in C01 with two future pressures, so the old one is explicitly marked superseded.
3. Re-checking H2 against the written code found that `post()` lives once on a shared `TransitionView`
   base, not on each view class. **The diagram was corrected to match the code**, not the reverse.
4. A review of the restructured code found a **regression introduced by C03 itself**: `AvailabilityView`
   read the clock twice, so a pending approval expiring between the two reads could be reported as
   available and as blocking in the same response. Fixed by resolving `now` once; pinned by a test that
   was confirmed to fail against the broken version.

**AS-IS → TO-BE delta:** seven `CHANGE` rows, four `KEEP`, three `VERIFY` (section J).

**Implementation changes:** four new modules — `lifecycle.py` (owns every `Reservation.status` write),
`availability.py` (owns the BR-02 definition, moved out of `models.py`), `approval.py` (owns the 24 h
window and the deadline), `notifications.py` (port + logging implementation, dispatched via
`transaction.on_commit`). `views.py` became four one-line subclasses of a shared `TransitionView`
adapter; `expire_pending_approvals` delegates to the lifecycle owner. **No model field changed and no
migration was generated.**

**Behaviour verification:** `pytest` → **61 passed** (the 52 C02 behaviour tests unchanged, plus 5
architecture-rule tests, 3 notification tests and 1 regression test). `manage.py check` → no issues.
`makemigrations --check --dry-run` → `No changes detected`. `scripts/demo_c02.sh` ran end to end against
a live server; every status code, error code and response shape matched the pre-refactor run, with only
ids and timestamps differing as they must between two runs. Full table in L1.

**Architecture conformance rule + result:** *only `lifecycle.py` may write `Reservation.status`, and no
domain module may import the web framework.* Checked by `scripts/check_architecture.py` (AST scan, also
runnable as `pytest src/reservations/tests/test_architecture.py`) → **passes**. Run against the
pre-refactor commit it reports the status writes J identified — six, the expiry command
included *(corrected 2026-10-21: "exactly the five")* — so the check is proven to detect the violation
it is meant to prevent.

**Remaining uncertainty / risk:**
- **REQ-04 under real parallelism** is still unverified and, by ADR-01, unguaranteed. The first
  reconsider-when trigger is a second concurrent user. *(Resolved 2026-10-21 — see* C03/C05 review
  fixes*.)*
- **BR-02 is not protected outside the application** — admin, shell or a second process can violate it.
- **Expiry still has no scheduler** (D9, DR-2): `EXPIRED` is materialised by a command somebody runs.
  Availability stays correct meanwhile because the deadline is data, but the two can disagree about the
  stored status.
- **The Notification Service is still a stub.** The boundary, the port and the after-commit ordering now
  exist and are tested; no real transport, retry policy or dead-letter handling does.
- **Authentication is still `actor_user_id` in the body** (D7, DR-5). It is now applied in one element
  per operation instead of four views, so replacing it is a contained change — but it is not done.

**Commit / tag:** the C03 design and the lifecycle-owner refactor are commit **`3d28f6e`** on branch
`c03-architecture`, on top of tag `v0.2` (`f764c83`); the review corrections above follow it on the same
branch. Baseline v0.2 behaviour is unchanged, so no new baseline tag is created — `v0.2` remains the tag
for the application's behaviour and `3d28f6e` identifies its C03 structure.

---

# C05 — DD Verification Evidence

**Unit under design:** Approval handling — the **Approval Policy** element of
[G2](architecture-and-decisions.md#g2--to-be-static-architecture) plus the approval paths of the
Reservation Lifecycle element. Requirements REQ-07 … REQ-10; rules BR-02, BR-03, BR-04, BR-05.

**Tests derived from DD:** nine design decisions produced ten tests in
`src/reservations/tests/test_approval_policy.py`.

| DD element | Test | Level |
|---|---|---|
| `deadline_for` contract (`now < deadline <= start_at`) | T-1 | unit |
| the two branches of the deadline algorithm | T-2 | unit |
| **AGREEMENT** — `is_live` equals membership of `live_q` | T-3 | component |
| **TOTALITY** — live ∪ overdue partitions every pending row | T-4 | component |
| reconciliation materialises only overdue rows, idempotently | T-5 | component |
| reconciliation does not change what the system means (DR-2) | T-6 | component |
| a `NULL` deadline is defined, not a crash | T-7, T-7b | unit + component |
| an effectively expired reservation cannot be cancelled (BR-03) | T-8 | component |
| the approval window is a variation point | T-9 | component |

**Unit/component tests executed:** `pytest` → **71 passed** (61 before C05, plus the ten above);
**80 passed** after the 2026-10-21 review fixes (T-9 strengthened, plus nine new tests listed there).
`manage.py check` → no issues. `makemigrations --check --dry-run` → `No changes detected` — the design
needed no schema change. `scripts/demo_c02.sh` ran end to end with all fourteen expected HTTP results
unchanged. `scripts/check_architecture.py` still passes, so the C05 work did not break the ADR-01
rule: the policy supplies predicates and the lifecycle element remains the only writer of
`Reservation.status`.

**Design ↔ implementation mismatch:** two, both found by writing the contract before reading the code.
The first was not reachable through the API in a normal run; the second was — an overdue pending
request stays open to cancel until its start, often for days — but no test had looked at that case.
*(Corrected 2026-10-21: this line first said neither was reachable.)*
1. A `PENDING_APPROVAL` with no `approval_deadline` crashed the decision path with
   `TypeError: '<=' not supported between instances of 'NoneType' and 'datetime.datetime'`, and the two
   SQL predicates both excluded it, so it was neither live nor overdue.
2. A reservation whose approval window had closed could still be cancelled and stored as `CANCELLED`,
   although BR-03 declares `EXPIRED` terminal.

**Resolution:** the **design won in both cases** and the code changed, because the specification
already said what should happen. `live_q` now requires a non-null deadline and `overdue_q` accepts null
or past, which makes the rule total; `cancel` consults the effective status and refuses with `EXPIRED`.
The tests are not vacuous: T-4 was run against the pre-DD predicates and fails there, and the two
behaviour changes were measured on the old code before being changed.

**Baseline consistency:** the C05 behaviour change was carried back into
[specification.md](specification.md) as a **clarification inside baseline v0.2**, not as a new
baseline. BR-03's first and last bullets had contradicted each other since C02 — one allowed a pending
request to be cancelled any time before the start, the other declared `EXPIRED` terminal — and a
pending request past its deadline satisfied both. C05 resolved the contradiction in favour of
terminality and the implementation was corrected to match, so no requirement was added. Updated: BR-03,
the OP-04 failure outcomes and verification examples, the v0.2 state diagram guard, and the Cancel row
of the consistency table. *(Corrected 2026-10-21.)* Tag `v0.2` (`f764c83`) marks the behaviour **as of
C02**: there, cancelling an overdue pending request returns `200 CANCELLED`. The behaviour after C05 —
`409 EXPIRED` — is identified by commit `6505316` (code) and `49e90eb` (specification). The
specification baseline stays v0.2 because the requirement text did not change, only an internal
contradiction in it was resolved; the application's behaviour did change, and no new tag was cut.

**Remaining design risk:**
- **The sweeper still has no scheduler.** C05 resolved *what `EXPIRED` means* — a projection being
  caught up with, now pinned by T-6 — but not *who runs the reconciliation*. Somebody still types the
  command. DR-2 is half closed.
- **`set_policy()` is process-global.** Tests that swap the policy must restore it, exactly like
  `notifications.set_port`. A settings-driven or request-scoped policy would be safer if a second
  policy ever ships.
- **The 24 h window still has no external source.** C05 gave it a home and made it injectable; it did
  not make it right.
- Carried out of C03 and unchanged: BR-02 unprotected outside the application, the notification
  transport, and `actor_user_id` instead of authentication. *(REQ-04 under true concurrency was on this
  list until the 2026-10-21 review fixes; it now holds within SQLite's 5 s busy timeout.)*

**Commit / tag:** C05 is commit **`6505316`** (design, code, tests) and **`49e90eb`** (the specification
clarification), on branch `c05-detailed-design`, on top of `ea9e794` (C03); `main` was fast-forwarded
to `49e90eb`. No tag: tag `v0.2` marks the C02 behaviour (see *Baseline consistency*). The review
fixes below follow on branch `c05-review-fixes`.

---

# C03/C05 review fixes (2026-10-21)

A review of C03 and C05 checked every claim against the code and re-ran the experiments. What it found,
and what changed:

| Finding | Evidence | Change |
|---|---|---|
| ADR-01, E2, E3 and Part A said two racing confirmations on SQLite "both write" and break BR-02 | Two threads held between the BR-02 probe and the write: never a double booking; the loser failed with `OperationalError: database is locked` (`500`), the winner got `200`. | BR-02 held, REQ-04 did not. The original text is kept (struck through in E2/E3) with a dated correction after it |
| The comparison missed the cheapest alternative, A + `BEGIN IMMEDIATE` | Django 5.2 `DATABASES[…]["OPTIONS"]["transaction_mode"]` | `transaction_mode = "IMMEDIATE"` in `settings.py`; [ADR-01 addendum](architecture-and-decisions.md#adr-01-addendum--2026-10-21-sqlite-immediate-transactions) |
| "REQ-04 can be tested only sequentially / a parallel test needs PostgreSQL" | the experiment itself | `tests/test_concurrency.py` (2 cases, real HTTP against a live server): exactly one `200` and one `409 OVERLAP`; 5/5 runs pass; the same test fails without IMMEDIATE (`[200, 500]`, `database is locked`) and on the default in-memory test DB (`database table is locked`), hence `TEST.NAME` is a file |
| `AvailabilityView` read the blocking set twice, so a commit between the reads could split the answer | code: two queries in one request, no transaction | `availability.assess()` returns the verdict and the list from one query; test counts one reservation query and fails on the old code (2 queries) |
| `check_architecture.py` missed `setattr`, `bulk_update`, `create(status=…)`, and exempted any file named `lifecycle.py` | code reading | detected now, exemption by path; 6 new tests; still reports all six writes at `f764c83` |
| L2 said the checker reports "exactly the five writes" at `f764c83` | the committed checker reports six (the expiry command too) | listing corrected |
| T-9 promised "the deadline and nothing else" but checked only the deadline | test reading | T-9 now runs `confirm` with the injected policy and compares the other four operations under both policies |
| H2 and K used names C05 had removed | `grep` in `src/` | H2 updated to the code; K keeps the C03 record with a note on the renames |
| C05 evidence: "tag v0.2 still marks the application's behaviour"; no commit hash; "neither mismatch reachable through the API" | `git show f764c83`: cancel of an overdue pending → `CANCELLED`; spec OP-04's own example (7 days ahead) | corrected above in the C05 section |

**Verification:** `pytest` → **80 passed**; `manage.py check` → no issues; `makemigrations --check
--dry-run` → `No changes detected` (the settings change needs no migration);
`scripts/check_architecture.py` → rules hold; `scripts/demo_c02.sh` against a live server → the same
fourteen HTTP results as before.

**Remaining risk:** a write lock held longer than SQLite's busy timeout (5 s) still ends in `500`;
writes are one at a time; `transaction_mode` is SQLite-only, so a move to PostgreSQL must add
`select_for_update()` or a constraint — `test_concurrency.py` is there to fail if it does not.
The test database is now one file (`src/test_db.sqlite3`), so two `pytest` runs in the same checkout
at the same time break each other; run one at a time. `check_architecture.py` still does not see
`Reservation(status=…)` followed by `save()`, `bulk_create`, or `update(**{"status": …})`.

**Commit:** **`4069177`** on branch `c05-review-fixes`, on top of `49e90eb`. (This line was added by the
following commit, because a commit cannot name its own hash.)

---

## C06 Internal Evidence Assessment

**Assessed baseline:** commit `51111fa` on `main` (C03 and C05 including the review fixes, on top of tag `v0.2`), assessed by
team **Office Reservation System** on 2026-10-22. Their completed form, with our owner disposition
added, is [c06-assessment-by-office-reservation.md](c06-assessment-by-office-reservation.md). Re-checked
by us on the same commit (2026-10-25, Python 3.12.14, Django 5.2.18, DRF 3.18.3): `pytest` → **80
passed**; `python scripts/check_architecture.py` → rules hold.

**Verification baseline for the commands below:** `main` at HEAD `093d516` (2026-11-08). `git diff --stat
51111fa HEAD -- src scripts/check_architecture.py requirements.txt pytest.ini` is empty, so the code and
tests under `src/`, the architecture checker, the dependency list and the pytest configuration are
unchanged since the assessed commit. Commands were run from the repository root with `.venv/bin/python`.

**Candidates raised:** the assessors recorded two as VERIFIED (F1, F3) and one as REJECTED CANDIDATE (F2):
- **F1** — architecture rules are validated automatically (`scripts/check_architecture.py`,
  `tests/test_architecture.py`). A confirmation of conformance, not a nonconformity.
- **F2** — no CI pipeline (they rejected it themselves).
- **F3** — dependencies may not be pinned. Their own verification line says this still "needs to be
  checked"; the content of `requirements.txt` was not inspected.

**Owner disposition (overview).** Criterion, from the C07–C08 assignment ("Defect / Finding = a proven
nonconformity with an accepted claim", `tasks/C07-C08.txt:115`): a **VERIFIED FINDING** is a reproduced
nonconformity with a C01–C05 claim on baseline `51111fa`; anything else is a **REJECTED CANDIDATE**. The
assessors marked F1 and F3 VERIFIED because the observations are true; we differ because neither
observation contradicts a C01–C05 claim (F1 confirms conformance, F3 concerns a property C01–C05 never
claimed).

| Finding | Assessors' result | Our verdict | Disposition | Reason |
|---|---|---|---|---|
| F1 | VERIFIED FINDING | REJECTED CANDIDATE (true observation, conformance, not a nonconformity) | ACCEPT observation — no change | True and reproduced, but it confirms conformance, so there is nothing to fix → [F1](#f1--architecture-is-validated-automatically) |
| F2 | REJECTED CANDIDATE | REJECTED CANDIDATE | REJECT — no change | No C01–C05 assignment asked for CI, and C06 lists "has no CI pipeline" among non-findings → [F2](#f2--no-ci-pipeline) |
| F3 | VERIFIED FINDING | REJECTED CANDIDATE (true observation, no C01–C05 claim violated) | REJECT — no change | `requirements.txt` has only `~=` constraints, but no C01–C05 claim requires a pinned, reproducible environment → [F3](#f3--dependencies-may-not-be-pinned) |

Owner for all three: team (Rent-a-Partner). The ACCEPTED / REJECTED column of the C06 form
([Owner disposition](c06-assessment-by-office-reservation.md#owner-disposition)) means ACCEPT / REJECT
here; for F1 the reclassification from VERIFIED FINDING to REJECTED CANDIDATE does not change the
decision recorded there ("ACCEPTED — no immediate change"): no change.

### F1 — Architecture is validated automatically

- **Claim:** none of C01–C05 is contradicted. The finding asserts that the architecture rules (C03) are
  checked automatically; it is a confirmation of conformance, not a claim that something fails.
- **Expected:** the repository keeps to the architectural boundaries (`Reservation.status` written only by
  `lifecycle.py`; no domain module depends on the web framework).
- **Observed:** `scripts/check_architecture.py` and `src/reservations/tests/test_architecture.py` exist and
  enforce those rules. Run on `main` (HEAD `093d516`, `src/` and the checker unchanged since `51111fa`):
  - `.venv/bin/python scripts/check_architecture.py` → `Architecture rules hold: Reservation.status is written only by lifecycle.py, and no domain module depends on the web framework.` (exit 0)
  - `.venv/bin/python -m pytest -q src/reservations/tests/test_architecture.py` → `11 passed in 0.02s` (exit 0)
- **Verify:** both commands above, on `main` (HEAD `093d516`), code and checker identical to `51111fa`
  (empty `git diff --stat 51111fa HEAD -- src scripts/check_architecture.py requirements.txt pytest.ini`).
  Same result as on `51111fa` (checker holds, 11 passed).
- **Disposition:** assessors VERIFIED FINDING; ours **REJECTED CANDIDATE (true observation, conformance,
  not a nonconformity)**, by the same criterion as F3: a finding is a proven nonconformity with an
  accepted claim, and F1 proves conformance. **ACCEPT observation — no change.** Reason: the statement
  is true and describes conformance, so there is nothing to fix. The C06 form records F1 as "ACCEPTED —
  no immediate change"; the reclassification does not change that decision. Owner: team (Rent-a-Partner).
- **Closure evidence:** no change needed. The evidence is the checker output and the 11 passing tests
  above. Limits of the checker (what it does not see) are listed under "Remaining evidence gaps".

### F2 — No CI pipeline

- **Claim:** none of C01–C05 is contradicted. The finding says tests are not run by a CI/CD pipeline; no
  C01–C05 requirement or claim promised one.
- **Expected (assessors):** a CI configuration file (e.g. `.github/workflows/` or `.gitlab-ci.yml`).
- **Observed:** no CI configuration in the repository. Run on `main` (HEAD `093d516`):
  - `ls .github .gitlab-ci.yml 2>&1` → `ls: cannot access '.github': No such file or directory` and
    `ls: cannot access '.gitlab-ci.yml': No such file or directory`
- **Verify:** the `ls` above on `main` (HEAD `093d516`); the assessors checked the tree of `51111fa`.
  The observation is true, but it is not a defect against C01–C05, and the C06 assignment explicitly lists
  "has no CI pipeline" among things that are not findings.
- **Disposition:** assessors REJECTED CANDIDATE ("can be set up later"); ours REJECTED CANDIDATE.
  **REJECT.** Reason: no C01–C05 assignment asked for CI. Owner: team (Rent-a-Partner).
- **Closure evidence:** no change (no-change decision). Tests are run by hand (`pytest`); nothing is
  claimed about automated runs.

### F3 — Dependencies may not be pinned

- **Claim:** none of C01–C05 is contradicted. The finding asserts a reproducible environment; C01–C05 did
  not require one. C01 offered it only as spike C "Reproducible build/config" (`tasks/C01.txt:132`), and
  the team chose spike A (Persistence).
- **Expected (assessors):** exact pinned versions in `requirements.txt`.
- **Observed:** `requirements.txt` exists but has only compatible-release `~=` constraints. Run on `main`
  (HEAD `093d516`):
  - `cat requirements.txt` →
    ```text
    Django~=5.2
    djangorestframework~=3.16
    pytest~=8.3
    pytest-django~=4.11
    ```
    i.e. `Django~=5.2` = ≥5.2,<6.0, likewise DRF, pytest, pytest-django; no exact pins, no lock file.
- **Verify:** `cat requirements.txt` above. The factual statement is true. The assessors' own verification
  line says the pinning "needs to be checked" and the content of `requirements.txt` was not inspected, so
  they recorded VERIFIED without verifying it; we did. Exact versions are recorded with many results (e.g.
  line 27 here: Django 5.2.17 / DRF 3.18.1; the 2026-10-21 rows of L1 in architecture-and-decisions.md:
  Django 5.2.18 / DRF 3.18.3); on `51111fa` re-checked 2026-10-25 with Django 5.2.18, DRF 3.18.3:
  `pytest` → 80 passed.
- **Disposition:** assessors VERIFIED FINDING (their own line says "needs to be checked"); ours: the
  observation is factually true but it is not a violation of any C01–C05 claim, so REJECTED CANDIDATE.
  **REJECT.** Reason: a reproducible environment was not required by C01–C05, and the finding was not
  technically verified by its authors. Owner: team (Rent-a-Partner).
- **Closure evidence:** no change (no-change decision). The residual risk, that a later install may pull
  newer minor versions than the ones recorded, is accepted; it is mitigated only by recording versions
  with results. Carried into part B as [R-02](#r-02--a-fresh-install-pulls-different-dependency-versions).

### Own observation (not raised by C06) — the Django admin bypasses the Lifecycle and BR-02

Not a C06 finding; recorded because the C07–C08 assignment asks that an unprotected admin/approval path
on the REQ-04 / BR-02 line be backed by a conclusion and an action.
- **Claim:** BR-02 / REQ-04 hold for the API paths only (Confirm, Approve through the Reservation
  Lifecycle); ADR-01 accepts that nothing outside the application protects BR-02 (accepted negative
  consequence 2).
- **Observed:** `/admin/` is mounted in `src/config/urls.py:5`, and `src/reservations/admin.py:12`
  `ReservationAdmin` is a plain `ModelAdmin` with no `readonly_fields`. Its form offers `status`,
  `start_at`, `end_at` and `approval_deadline` for editing (checked 2026-11-08 on HEAD `093d516` with
  `ReservationAdmin.get_form(...).base_fields` in `manage.py shell`), and it saves through generic
  `ModelForm` code, bypassing the Lifecycle and the BR-02 check. `check_architecture.py` cannot see it.
- **Disposition:** **DEFER — no code change at the reporting baseline**, carried into part B as a
  Security / Privacy risk —
  [R-01](#r-01--the-django-admin-edits-reservations-around-the-lifecycle-and-br-02). Owner: Pavel Marszalek.
- **Trigger:** any real admin/staff user, or any data edited via `/admin/`.
- **Candidate action:** `readonly_fields` for `status`, `start_at`, `end_at`, `approval_deadline` in
  `ReservationAdmin`. *(Superseded 2026-11-08 by the
  [R-01 treatment](#r-01--the-django-admin-edits-reservations-around-the-lifecycle-and-br-02): the form also
  offers `companion`, `approval_requested_at` and `decided_by`, and the add view creates a reservation
  with any of them, so the treatment adds these three fields and `has_add_permission` → `False`.)*
- **Status:** **NOT VERIFIED** — no mitigation exists, so nothing is verified as closed.

**Actions / justified no-change decisions:** no code or document change follows from F1–F3; the reasons
are above. No C06 finding was fixed in code; none is a nonconformity (see the criterion above the
overview table). Two remarks on the checklist itself, recorded so the YES answers are not read as
stronger evidence than they are:
- **Q1–Q3 (C04)** are answered YES for a quality concern the assessors chose themselves
  (concurrency). C04 did not take place for our seminar group (public holiday on the seminar day), so
  no quality concern, criterion or measurement was ever set; the correct answer is **N/A**. The
  concurrency behaviour they point to is REQ-04, verified under C03 (`tests/test_concurrency.py`).
- Most other YES answers rest on the presence of files rather than an inspected code path or a run, so
  we do not count them as additional verification beyond what this file records.

**Remaining evidence gaps** (known to us; none was raised by the assessment):
- REQ-04 holds only within SQLite's 5 s busy timeout; a longer-held write lock still ends in `500`.
  **NOT VERIFIED** — not tested. → [R-03](#r-03--req-04-is-verified-only-within-the-tested-limits)
- The approval path (REQ-09 re-check of BR-02) is serialised the same way but has no parallel test.
  **NOT VERIFIED** under concurrency (reasoned from the code, not measured). → [R-03](#r-03--req-04-is-verified-only-within-the-tested-limits)
- `check_architecture.py` does not see `Reservation(status=…)` followed by `save()`, `bulk_create`, or
  `update(**{"status": …})`.
- The Notification Service is a logging stub; no transport, retry or dead-letter policy. → known limit
  [K-1](#known-design-limits-facts-not-assumptions)
- Expiry has no scheduler; `manage.py expire_pending_approvals` is run by hand (DR-2). → known limit
  [K-2](#known-design-limits-facts-not-assumptions)
- The actor is `actor_user_id` in the request body, not authentication (D7, DR-5). → assumption
  [A-3](#assumptions)
- The Django admin (`/admin/`, `src/reservations/admin.py:12`) edits `status`, the interval and
  `approval_deadline` directly, bypassing the lifecycle and BR-02 (ADR-01, accepted negative
  consequence 2). It can also change `companion` and add new reservations (checked 2026-11-08, see
  R-01). `check_architecture.py` does not cover it. **NOT VERIFIED** (no mitigation) — see
  [Own observation](#own-observation-not-raised-by-c06--the-django-admin-bypasses-the-lifecycle-and-br-02)
  and [R-01](#r-01--the-django-admin-edits-reservations-around-the-lifecycle-and-br-02).

## C07–C08 Risk Assessment (part B)

**Reporting baseline:** tag `c08-review`, content commit `ad2cee7` on `main`, 2026-11-09 (the tag points at the follow-up commit that only records this hash) — the same baseline as
part A ([technical-design-review.md](technical-design-review.md#reporting-baseline)). `git diff --stat
51111fa c08-review -- src scripts requirements.txt pytest.ini` lists only the new `scripts/demo_c08.sh`,
so the code, the tests and the dependency list are the ones C06 assessed. The commands recorded
[below](#commands-run-for-this-section) were run on 2026-11-08 from the repository root on a clean tree
at `c5d90d9`, one pytest process at a time; `c5d90d9` → `ad2cee7` changes only documents, and on `ad2cee7` (2026-11-09) `pytest` → 80 passed, `test_concurrency.py` → 2 passed, `scripts/demo_c08.sh` → exit 0; the incident in [I-01](#issues-already-happened) happened
outside them.

**Naming:** R-01 … R-04 here are risks. They are not the system responsibilities R-1 … R-7 in
[C2](architecture-and-decisions.md#c2--system-responsibilities).

**Classification** (assignment B3–B4). Likelihood **L** and impact **I** are each 1 (low), 2 (medium)
or 3 (high). Priority = L × I: **1–2 LOW, 3–4 MEDIUM, 6–9 HIGH**. Initial = before the treatment;
expected residual = after the planned treatment; actual residual = only after the treatment exists
and a run shows it works. Where it does not, the actual residual is **NOT VERIFIED** and keeps the
initial score. Owners and due dates were set by the team on 2026-11-08; every due date is "by CP2" (the exact CP2 date is not fixed yet). The acceptance owner of every residual risk is the team.

| ID | Category | Initial | Strategy | Actual residual |
|---|---|---|---|---|
| [R-01](#r-01--the-django-admin-edits-reservations-around-the-lifecycle-and-br-02) | Security / Privacy | L=1, I=3 → MEDIUM (3) | MITIGATE | **NOT VERIFIED** — stays MEDIUM (3) |
| [R-02](#r-02--a-fresh-install-pulls-different-dependency-versions) | Release / Operation | L=1, I=2 → LOW (2) | ACCEPT | LOW (2), unchanged |
| [R-03](#r-03--req-04-is-verified-only-within-the-tested-limits) | Technical / Quality | L=3, I=3 → HIGH (9) | MITIGATE | L=1, I=3 → MEDIUM (3), partly verified |
| [R-04](#r-04--a-two-person-team-carries-the-scope-of-a-larger-team) | People / Resources | L=2, I=2 → MEDIUM (4) | MITIGATE | **NOT VERIFIED** — stays MEDIUM (4) |

### R-01 — The Django admin edits reservations around the Lifecycle and BR-02

| Item | Record |
|---|---|
| **ID & statement** | **R-01:** the admin at `/admin/` lets a staff user add or change a reservation with any `status`, `companion` and interval → the save skips the Lifecycle and the BR-02 check → overlapping blocking reservations (or a state the statechart forbids) are stored without any error, so BR-02 no longer holds in the data |
| **Category** | Security / Privacy — an admin permission wider than the domain rules allow |
| **Initial L/I / priority** | **L=1, I=3 → MEDIUM (3).** The path exists: `/admin/` is mounted (`src/config/urls.py:5`) and `ReservationAdmin` (`src/reservations/admin.py:12`) is a plain `ModelAdmin`. Checked today on `c5d90d9`: `get_readonly_fields()` → `()`; `has_add_permission` → `True`; the add form and the change form both offer `activity`, `approval_deadline`, `approval_requested_at`, `companion`, `customer`, `decided_by`, `end_at`, `start_at`, `status`. Changing `companion` alone moves a reservation onto another companion's calendar. L: the local development database has one superuser, but the API and the demo never use the admin, there are no real staff users, and a conflict needs a deliberate edit. I: if it happens, BR-02, the main invariant of part A, is broken in the stored data and nothing reports it (`check_architecture.py` reads code, not admin forms). Low likelihood, but the impact is on the core invariant, so it gets a response (B4 note) |
| **Strategy** | **MITIGATE** — keep the admin (the README documents it), but take away every way it can write the fields that decide BR-02 and the lifecycle. The change is small and local. AVOID (unmount `/admin/`) would also work and is the fallback |
| **Treatment & owner / due** | In `ReservationAdmin`: `readonly_fields` for `companion`, `start_at`, `end_at`, `status`, `approval_deadline`, `approval_requested_at`, `decided_by`, and `has_add_permission` returning `False` (with `start_at`/`end_at`/`companion` read-only, the add form could not fill these NOT NULL fields and would fail anyway). A test covers both views: the change form offers none of these fields, and the add view is refused. Owner: Pavel Marszalek; due: by CP2 |
| **Treatment evidence** | None yet — no code change on `c08-review`. Expected evidence: the new test in `src/reservations/tests/` and a passing `pytest` |
| **Expected residual** | L=1, I=1 → LOW (1): through the admin a reservation can then only be deleted, or have `activity` / `customer` edited; none of this can create an overlap or a forbidden state. Writes through `manage.py shell` or straight into the database stay possible (ADR-01, accepted consequence 2), but only for developers |
| **Actual residual** | **NOT VERIFIED** — the treatment does not exist; stays L=1, I=3 → MEDIUM (3) |
| **Acceptance & contingency** | Until the fix, the risk is accepted for the defence; acceptance owner: the team (Rent-a-Partner). Contingency: do not add or change reservations through `/admin/` in the demo; if a row was edited there, treat the local database as untrusted and recreate it (`src/db.sqlite3` is local; `*.sqlite3` is in `.gitignore`) |
| **Monitoring / trigger** | Trigger: any real admin/staff user, any data added or edited via `/admin/`, any change to `admin.py` or `urls.py`, or a second process with write access to the reservation table (ADR-01 reconsider trigger). Check at each new baseline with the admin command [below](#commands-run-for-this-section) |

### R-02 — A fresh install pulls different dependency versions

| Item | Record |
|---|---|
| **ID & statement** | **R-02:** `requirements.txt` has only `~=` ranges and no lock file ([C06 F3](#f3--dependencies-may-not-be-pinned)) → a fresh install before the defence pulls a newer version that changes behaviour → `pytest` or `scripts/demo_c08.sh` fails on that machine and no longer matches the recorded results |
| **Category** | Release / Operation — reproducible build |
| **Initial L/I / priority** | **L=1, I=2 → LOW (2).** L: drift is real — a fresh install today resolves Django **5.2.19**, while part A was recorded on 5.2.18 (and the 2026-09-14 run under "Observed result" above on 5.2.17 / DRF 3.18.1). A break is less likely: the ranges stay inside Django 5.2 LTS (`~=5.2` = <6.0), DRF 3.x and pytest 8.x (8.4.2 is the last 8.x; pytest 9 is excluded), and the fresh set passed 80 of 80 today. I: a failing fresh install hits the demo on that machine, but recovery is quick and known (install the recorded exact versions); the existing `.venv` is not affected |
| **Strategy** | **ACCEPT** — as decided in C06 F3: C01–C05 did not require a reproducible environment, the event is unlikely, and the contingency is ready |
| **Treatment & owner / due** | No treatment beyond what exists: exact versions are recorded with every result (part A: Python 3.14.7, Django 5.2.18, DRF 3.18.3, pytest 8.4.2; pytest-django 4.14.0, checked today). Fresh-install check (Monitoring): owner Tobias Janča, due by CP2. A constraints/lock file with these versions is not decided; Tobias Janča decides by CP2 whether to add it |
| **Treatment evidence** | Fresh-install check, 2026-11-08 (commands [below](#commands-run-for-this-section)): a throwaway venv resolves Python 3.14.7, Django 5.2.19, DRF 3.18.3, pytest 8.4.2, pytest-django 4.14.0, and its pytest run in this checkout gives `80 passed in 13.78s`. This is monitoring, not a mitigation |
| **Expected residual** | L=1, I=2 → LOW (2) — ACCEPT does not lower the score |
| **Actual residual** | L=1, I=2 → LOW (2), unchanged. A lock file does not exist, so nothing is claimed for it |
| **Acceptance & contingency** | Acceptance owner: the team (Rent-a-Partner) (the C06 F3 disposition was made by the team). Contingency: `.venv/bin/pip install Django==5.2.18 djangorestframework==3.18.3 pytest==8.4.2 pytest-django==4.14.0` (pip 26.2.1 is in `.venv`; with uv: `VIRTUAL_ENV=.venv uv pip install` with the same pins), then run `pytest` again |
| **Monitoring / trigger** | Before the defence, repeat the fresh-install check. Trigger: a fresh install resolves a new minor version, any test fails on a fresh install, or the demo machine gets a new Python version |

### R-03 — REQ-04 is verified only within the tested limits

| Item | Record |
|---|---|
| **ID & statement** | **R-03:** SQLite allows one writer at a time → two requests that write the same companion's calendar at the same time leave the loser with `500` instead of `409 OVERLAP` → REQ-04 is not met |
| **Category** | Technical / Quality — concurrency, REQ-04, on the current SQLite setup |
| **Initial L/I / priority** | **L=3, I=3 → HIGH (9)**, before the treatment (2026-10-21). L: measured — with SQLite's default deferred transactions the race gave `200` + `500 database is locked` in 3 of 3 runs per case ([ADR-01 addendum](architecture-and-decisions.md#adr-01-addendum--2026-10-21-sqlite-immediate-transactions)). I: REQ-04 is the accepted claim at the centre of part A; BR-02 itself held (SQLite serialises writers), but the claimed `409 OVERLAP` did not |
| **Strategy** | **MITIGATE** — serialise the writers and prove it with a real race test |
| **Treatment & owner / due** | Done (`4069177`, 2026-10-21): `"OPTIONS": {"transaction_mode": "IMMEDIATE"}` (`src/config/settings.py:56`) and `src/reservations/tests/test_concurrency.py` (two threads, real HTTP to a live server, a 0.2 s hold at line 16, oracle at line 86). Still planned, for what the test does not cover: (a) a behaviour change for a lock held longer than SQLite's 5 s busy timeout — map `OperationalError: database is locked` to a defined response (`409`, or `503` with a retry hint) instead of an unhandled `500`, with a test that holds the lock longer than 5 s; (b) a parallel test that races Approve against Confirm on the same slot; (c) a race with more than two requests. Owner: Pavel Marszalek; due: by CP2 |
| **Treatment evidence** | Run today on `c5d90d9`: `test_concurrency.py` → `2 passed in 1.55s` (exit 0), then 5 more runs one after another → `2 passed` each (1.49–1.50 s); whole suite → `80 passed in 13.61s`. Negative control: without `IMMEDIATE` the same test gave `[200, 500]` ([C03/C05 review fixes](#c03c05-review-fixes-2026-10-21)); not repeated on this baseline, because it needs a code change |
| **Expected residual** | L=1, I=2 → LOW (2), only once (a) exists and passes: then a lock held too long ends in a defined refusal instead of a crash. (b) and (c) only extend the verified scope; they do not change I |
| **Actual residual** | **L=1, I=3 → MEDIUM (3), partly verified.** L is lowered for the tested path — two racing Confirms, direct and with approval — because the treatment exists and the race test passes (6 of 6 runs today; it failed without the treatment). I stays 3, because the consequence when it does happen (REQ-04 broken, `500` instead of `409`) is the same. The busy-timeout case, Approve under concurrency and more than two writers are **NOT VERIFIED**; that is why this is only partly verified |
| **Acceptance & contingency** | The MEDIUM residual is accepted for the CP1 defence; acceptance owner: the team (Rent-a-Partner). Reason: the demo has one user (assumption A-1) and a confirmation transaction holds the lock for milliseconds, far below 5 s. Contingency: a failing race test is a trigger, not something to re-run until it passes — stop claiming REQ-04 as verified, record an issue in this file, and update the part A / part C status |
| **Monitoring / trigger** | Trigger: `test_concurrency.py` fails; a `500` with `database is locked` appears; `DATABASES` in `settings.py` changes; ADR-01 reconsider triggers (more than one concurrent user or a load test with overlapping confirmations, a second process writing the reservation table). A move to PostgreSQL: `transaction_mode` is SQLite-only, and without `select_for_update()` or the exclusion constraint both racing requests could win — a real double booking (ADR-01 addendum); then this risk must be assessed again |

### R-04 — A two-person team carries the scope of a larger team

| Item | Record |
|---|---|
| **ID & statement** | **R-04:** the team has two members, while the other teams in the seminar group have three or four, and the assignments expect the same outputs from every team → the remaining work does not fit into the time before CP2 → actions slip or get done with less verification than planned |
| **Category** | People / Resources — team capacity |
| **Initial L/I / priority** | **L=2, I=2 → MEDIUM (4).** L: the scope is per team, not per person (C07–C08 asks every team for parts A, B and C), and the open work is real: the R-01 fix, step (a) of R-03, part C (status report) and the CP2 work, all still open (owners set on 2026-11-08, due by CP2, no dated plan yet). It is a realistic possibility, not a sure thing, because the core of the system and its evidence already exist. I: a delay or a narrower verification hurts schedule and quality, but recovery is realistic — the 80 automated tests, `scripts/check_architecture.py` and `scripts/demo_c08.sh` repeat the main checks with one command each |
| **Strategy** | **MITIGATE** — spend the limited capacity where the risk is highest and keep checks automatic |
| **Treatment & owner / due** | (1) Order the open actions by risk priority from this register (R-01 and R-03 (a) first) and do not add features beyond the C01–C05 obligations. (2) Keep every claim backed by a test or a script, so that re-checking costs no extra people. (3) Before CP2, write a short work plan with owners and dates (part C, slide 03). Owner: Tobias Janča; due: by CP2 |
| **Treatment evidence** | (2) exists: `pytest` → 80 passed, `check_architecture.py` → rules hold, `scripts/demo_c08.sh` → exit 0 (part A reporting baseline). (1) exists as the order of the part C action plan (P1 = R-01, P2 = R-03 (a)); (3) does not exist yet |
| **Expected residual** | L=1, I=2 → LOW (2), once the work plan exists and the high-priority actions are done by their dates |
| **Actual residual** | **NOT VERIFIED** — no work plan and no completed action yet; stays L=2, I=2 → MEDIUM (4) |
| **Acceptance & contingency** | Acceptance owner: the team (Rent-a-Partner). Contingency: if an action cannot be done in time, narrow it openly — keep the risk at its current score, mark the claim NOT VERIFIED and report it in part C, rather than present it as done |
| **Monitoring / trigger** | Review at every seminar. Trigger: an action misses its due date, new mandatory scope arrives (CP2), or one member is unavailable for a longer time |

### Issues (already happened)

- **I-01 — The test database is one shared file.** `TEST.NAME` is `src/test_db.sqlite3`
  (`src/config/settings.py:58`), so two pytest processes in the same checkout break each other. Expected
  since 2026-10-21 ([C03/C05 review fixes](#c03c05-review-fixes-2026-10-21), "Remaining risk"). It
  happened on 2026-11-08 during a parallel run of agents, outside the commands recorded in this section:
  two pytest processes ran in this checkout at the same time and one failed with `attempt to write a
  readonly database`. Not reproduced on purpose (it needs that parallel run). Not a nonconformity with
  C01–C05: no claim covers parallel test runs, and the file is needed for the REQ-04 race test (ADR-01
  addendum). Workaround: one pytest at a time (part A states this; `scripts/demo_c08.sh` runs its pytest
  calls one after another). Possible fix: a per-process test database name, which needs a change in
  `settings.py`. Owner: Pavel Marszalek. **Open.**
- **No open proven defect against C01–C05.** Checked today on `c5d90d9`: `pytest` → 80 passed,
  `check_architecture.py` → rules hold; C06 raised no nonconformity
  (see [above](#c06-internal-evidence-assessment)). The items in "Remaining evidence gaps" are missing evidence (NOT VERIFIED), not reproduced failures.
  The admin path ([R-01](#r-01--the-django-admin-edits-reservations-around-the-lifecycle-and-br-02))
  exists, but no conflicting reservation has been made through it, and ADR-01 accepted it as a known
  consequence, so it is kept as a risk. If the team decides that BR-02 must hold for the admin too, it
  becomes a defect.

### Assumptions

- **A-1** — The demo has one user at a time and there are no concurrent real users (basis of ADR-01 and
  of accepting R-03). If it stops being true, the ADR-01 reconsider triggers apply.
- **A-2** — The demo runs on a machine with the recorded environment and an installed `.venv` (R-02). Which machine: the one where the part A results were recorded (Pavel Marszalek's); a second machine is not prepared.
- **A-3** — The API is reached only from the same machine, so the missing authentication (D6) and the
  actor in the request body (D7) are accepted CP1 scope, not a risk. Basis: `manage.py runserver`
  without an address binds to `127.0.0.1:8000` (`Command.default_addr` = `127.0.0.1`; the README runs it
  that way), and `scripts/demo_c02.sh` binds `127.0.0.1` explicitly. `ALLOWED_HOSTS` (default
  `localhost,127.0.0.1`, `src/config/settings.py:8`) only adds a check of the `Host` header; it does not
  decide where the server listens. It becomes a Security risk as soon as the API is reachable by others
  (DR-5).

### Known design limits (facts, not assumptions)

- **K-1** — The Notification Service is a logging stub (`src/reservations/notifications.py:20`), so no
  external service is involved in the demo. Transport, retry and dead-letter policy are out of CP1 scope.
- **K-2** — Expiry has no scheduler, and this does not break BR-02: a pending request stops blocking at
  its deadline because the blocking query checks the deadline at read time (`policy.live_q(now)`,
  `src/reservations/availability.py:25`). Until someone runs `manage.py expire_pending_approvals`, the
  stored status of an overdue request is still `PENDING_APPROVAL` (DR-2).

### Commands run for this section

2026-11-08, repository root, `c5d90d9`, clean tree, one pytest process at a time. The fresh venv was
created in a scratch directory outside the repository; `mktemp -d` stands in for that path here.

```text
$ .venv/bin/python -m pytest -q src/reservations/tests/test_concurrency.py
..                                                                       [100%]
2 passed in 1.55s                                                        (exit 0)

$ for i in 1 2 3 4 5; do .venv/bin/python -m pytest -q -p no:cacheprovider src/reservations/tests/test_concurrency.py | tail -1; done
2 passed in 1.50s
2 passed in 1.49s
2 passed in 1.49s
2 passed in 1.49s
2 passed in 1.49s

$ .venv/bin/python -m pytest -q
80 passed in 13.61s                                                      (exit 0)

$ .venv/bin/python scripts/check_architecture.py
Architecture rules hold: Reservation.status is written only by lifecycle.py,
and no domain module depends on the web framework.                       (exit 0)

$ .venv/bin/python -c "import sys, django, rest_framework, pytest, pytest_django; print(sys.version.split()[0], django.__version__, rest_framework.__version__, pytest.__version__, pytest_django.__version__)"
3.14.7 5.2.18 3.18.3 8.4.2 4.14.0

$ FRESH="$(mktemp -d)/venv"
$ uv venv -q -p /usr/bin/python3 "$FRESH"
$ VIRTUAL_ENV="$FRESH" uv pip install -q -r requirements.txt
$ "$FRESH/bin/python" -c "import sys, django, rest_framework, pytest, pytest_django; print(sys.version.split()[0], django.__version__, rest_framework.__version__, pytest.__version__, pytest_django.__version__)"
3.14.7 5.2.19 3.18.3 8.4.2 4.14.0
$ "$FRESH/bin/python" -m pytest -q -p no:cacheprovider
80 passed in 13.78s                                                      (exit 0)

$ cd src && ../.venv/bin/python manage.py shell -c "
from django.contrib import admin
from django.contrib.auth.models import User
from django.test import RequestFactory
from reservations.models import Reservation
ma = admin.site._registry[Reservation]
r = RequestFactory().get('/admin/'); r.user = User.objects.filter(is_superuser=True).first()
obj = Reservation.objects.first()
print('readonly', ma.get_readonly_fields(r), 'add_perm', ma.has_add_permission(r))
print('add form', sorted(ma.get_form(r).base_fields))
print('change form', sorted(ma.get_form(r, obj, change=True).base_fields))"
8 objects imported automatically (use -v 2 for details).

readonly () add_perm True
add form ['activity', 'approval_deadline', 'approval_requested_at', 'companion', 'customer', 'decided_by', 'end_at', 'start_at', 'status']
change form ['activity', 'approval_deadline', 'approval_requested_at', 'companion', 'customer', 'decided_by', 'end_at', 'start_at', 'status']

$ .venv/bin/python -c "from django.core.management.commands.runserver import Command; print(Command.default_addr, Command.default_port)"
127.0.0.1 8000

$ git diff --stat 51111fa c08-review -- src scripts requirements.txt pytest.ini
 scripts/demo_c08.sh | 31 +++++++++++++++++++++++++++++++
 1 file changed, 31 insertions(+)

```
