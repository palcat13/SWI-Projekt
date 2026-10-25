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

**Verified findings:** the assessors recorded two as VERIFIED (F1, F3) and one as REJECTED CANDIDATE (F2):
- **F1** — architecture rules are validated automatically (`scripts/check_architecture.py`,
  `tests/test_architecture.py`). A confirmation of conformance, not a defect.
- **F2** — no CI pipeline (they rejected it themselves).
- **F3** — dependencies may not be pinned. Their own verification line says this still "needs to be
  checked"; the content of `requirements.txt` was not inspected.

**Owner disposition:**

| Finding | Disposition | Reason / evidence |
|---|---|---|
| F1 | ACCEPTED — no immediate change | Reason: it describes conformance, not a defect, so there is nothing to change. True as stated: on `51111fa` the checker reports "Architecture rules hold" and `test_architecture.py` gives 11 passed. Nothing to change. |
| F2 | REJECTED | No C01–C05 assignment asked for CI, and the C06 assignment lists "has no CI pipeline" among things that are not findings. |
| F3 | REJECTED | The observation is literally true: `requirements.txt` has no exact pins, only compatible-release `~=` (`Django~=5.2` = ≥5.2,<6.0, likewise DRF, pytest, pytest-django). Rejected because a reproducible environment was not required by C01–C05: C01 offered it only as spike C "Reproducible build/config" (`tasks/C01.txt:132`) and the team chose spike A (Persistence). The finding was also not technically verified (their verification says the pinning still "needs to be checked"). Exact versions are recorded with many results (e.g. line 27 here; the 2026-10-21 rows of L1 in architecture-and-decisions.md). |

**Actions / justified no-change decisions:** no code or document change follows from F1–F3; the reasons
are in the table. Two remarks on the checklist itself, recorded so the YES answers are not read as
stronger evidence than they are:
- **Q1–Q3 (C04)** are answered YES for a quality concern the assessors chose themselves
  (concurrency). C04 did not take place for our seminar group (public holiday on the seminar day), so
  no quality concern, criterion or measurement was ever set; the correct answer is **N/A**. The
  concurrency behaviour they point to is REQ-04, verified under C03 (`tests/test_concurrency.py`).
- Most other YES answers rest on the presence of files rather than an inspected code path or a run, so
  we do not count them as additional verification beyond what this file records.

**Remaining evidence gaps** (known to us; none was raised by the assessment):
- REQ-04 holds only within SQLite's 5 s busy timeout; a longer-held write lock still ends in `500`.
- The approval path (REQ-09 re-check of BR-02) is serialised the same way but has no parallel test.
- `check_architecture.py` does not see `Reservation(status=…)` followed by `save()`, `bulk_create`, or
  `update(**{"status": …})`.
- The Notification Service is a logging stub; no transport, retry or dead-letter policy.
- Expiry has no scheduler; `manage.py expire_pending_approvals` is run by hand (DR-2).
- The actor is `actor_user_id` in the request body, not authentication (D7, DR-5).

