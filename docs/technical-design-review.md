# Technical Design Review — C07–C08, part A

A summary of the technical state of Rent-a-Partner at the reporting baseline. It follows one line
through the project: **REQ-04 + BR-02** (Confirm must never produce two overlapping confirmed
reservations) → **ADR-01** (one Lifecycle element writes the status and checks BR-02 inside the same
transaction) → **C05 Approval Policy** (the deadline rule, BR-02 checked again at Approve) → **tests**
(touching intervals pass, overlap is refused, a real race has exactly one winner) → **C06** (what the
assessors found and what we decided).

## Reporting baseline

| Item | Value |
|---|---|
| **Reporting baseline** | tag **`c08-review`**, content commit `8eaeb40`, 2026-11-09 (the tag points at the follow-up commit that only records this hash in parts A, B and C) — one baseline for part A, part B (risk register) and part C (`docs/c08-project-status.pptx`) |
| **C06 assessed baseline** | commit `51111fa` (assessed by Office Reservation System, 2026-10-22) |
| **Old → new** | `git diff --stat 51111fa c08-review -- src scripts/check_architecture.py requirements.txt pytest.ini` is empty (checked against `8eaeb40`): code, tests, checker, dependencies and pytest configuration are the same as in the assessed baseline. No C06 finding was fixed in code, because none is a nonconformity ([step 5](#step-5--c06-findings-and-our-decision)) |
| **Environment** | Python 3.14.7, Django 5.2.18, DRF 3.18.3, pytest 8.4.2 |
| **Whole suite** | `.venv/bin/python -m pytest -q` → **80 passed** (on `8eaeb40`, clean tree, 2026-11-09; also 80 passed on `51111fa`) |
| **Demo** | `scripts/demo_c08.sh` → exit 0 on `8eaeb40`, 2026-11-09: (a) 3 passed · (b) 2 passed · (c) 2 passed · (d) 12 passed · (e) 11 passed + `Architecture rules hold` |

**Note:** do not run any other pytest in this checkout at the same time. The test
database is one file, `src/test_db.sqlite3` ([`settings.py:58`](../src/config/settings.py#L58)), so
two pytest processes break each other.

## Step 1 — Scope and accepted behaviour

Rent-a-Partner books a **companion** (a person with their own account) for a social activity in a
given time interval. The actors are Customer, Companion and Administrator; the Notification Service is
outside the system and only stubbed. We pick the operation **OP-03 Confirm**, because that is where a
draft turns into a real booking of the companion, so that is where the main rule must hold: **BR-02 —
one companion can never have two blocking reservations that overlap**. Intervals are half-open
(BR-01), so 10–11 and 11–12 do not overlap. **REQ-04** says that when two overlapping drafts are
confirmed at the same time, exactly one becomes `CONFIRMED` and the other gets `409 OVERLAP` and stays
`DRAFT`. The C02 change (Approval) split Confirm in two for companions who approve requests: the
request goes to `PENDING_APPROVAL`, which also blocks the slot until its deadline, so REQ-04 covers that
step too.

Sources: [OP-03 — Confirm Reservation](specification.md#op-03--confirm-reservation) (REQ-04,
pre/postconditions, verification examples), [Domain rules and invariants](specification.md#domain-rules-and-invariants)
(BR-01, BR-02) and the statechart in [Reservation lifecycle (v0.2)](specification.md#reservation-lifecycle-v02),
[C02 change impact](specification.md#c02-change-impact),
[OP-05 — Approve](specification.md#op-05--approve-reservation-new),
[Actors and system boundary](specification.md#actors-and-system-boundary).

What we admit: the actor is sent as `actor_user_id` in the request body, there is no authentication
(D6/D7). And inside baseline v0.2 one behaviour changed in C05 (an overdue pending request is
`EXPIRED`, it cannot be cancelled), see [C05 — DD Verification Evidence](evidence-and-evolution.md#c05--dd-verification-evidence).

## Step 2 — Architecture

In the original code (AS-IS) one HTTP view did everything: it checked BR-02 and then wrote the status
as two separate statements with nothing locking in between, and three views each decided the same
rule on their own. That gave us two drivers: BR-02 must hold under concurrency (DR-1) and every status
change must have one owner (DR-4). We compared two options: **A** — one application element, the
Lifecycle, is the only code that writes `Reservation.status` and it checks BR-02 in the same
transaction; **B** — a PostgreSQL exclusion constraint in the database. **ADR-01 chose A.** B can only
cover confirmed reservations, because a database constraint cannot depend on the current time and the
pending part of BR-02 does (it blocks only until the deadline). B would also force everyone to run
PostgreSQL. In the 2026-10-21 review we measured the race on SQLite: no double booking happened, but
the losing request got `500` instead of `409`. The fix was `BEGIN IMMEDIATE` (the transaction takes
the write lock at the start), recorded as the ADR-01 addendum.

Sources: [E2 — the alternatives against the drivers](architecture-and-decisions.md#e2--the-alternatives-against-the-drivers),
[ADR-01](architecture-and-decisions.md#adr-01--where-the-authoritative-confirmation-decision-is-made-and-what-enforces-br-02-under-concurrency)
with its [addendum](architecture-and-decisions.md#adr-01-addendum--2026-10-21-sqlite-immediate-transactions),
the sequence diagram [H1](architecture-and-decisions.md#h1--design-sequence-diagram-confirm-reservation),
and in code [`lifecycle.py:58`](../src/reservations/lifecycle.py#L58) `confirm()` — transaction at
[`:66`](../src/reservations/lifecycle.py#L66), BR-02 check at [`:82`](../src/reservations/lifecycle.py#L82),
the single status write at [`:95`](../src/reservations/lifecycle.py#L95) — and
[`settings.py:56`](../src/config/settings.py#L56) with `"transaction_mode": "IMMEDIATE"`. BR-02 itself
is defined in one place, [`availability.py:12`](../src/reservations/availability.py#L12). See also
AS-IS [A3 — conflict → rejection](architecture-and-decisions.md#a3--one-important-failure-path-conflict--rejection),
static view [G2](architecture-and-decisions.md#g2--to-be-static-architecture),
[L2 — architecture conformance](architecture-and-decisions.md#l2--architecture-conformance).

The ADR-01 rule is checked automatically:

```bash
.venv/bin/python scripts/check_architecture.py
# Architecture rules hold: Reservation.status is written only by lifecycle.py, ...
```

What we admit: nothing outside the application protects BR-02. The Django admin at `/admin/`
([`admin.py:12`](../src/reservations/admin.py#L12)) lets a staff user edit `status`, the interval and
`approval_deadline` directly, so a double booking can be made there, and the checker cannot see it.
ADR-01 accepted this as a known consequence; we recorded it as our own observation, deferred to part B,
**NOT VERIFIED** (no mitigation yet) — see [Own observation](evidence-and-evolution.md#own-observation-not-raised-by-c06--the-django-admin-bypasses-the-lifecycle-and-br-02).
`IMMEDIATE` exists only on SQLite; a move to PostgreSQL needs `select_for_update()` or the constraint.

## Step 3 — Detailed Design

The C05 unit is the **Approval Policy** and the approve/reject code in the Lifecycle. Its main
contract is the deadline: `deadline_for` returns `min(now + 24 h, start_at)`, so the deadline is always
after now and never after the start ([`approval.py:40`](../src/reservations/approval.py#L40)). The
question "is this pending request still live?" is answered both in Python (`is_live`) and in SQL
(`live_q`, `overdue_q`), and the contract requires that both give the same answer and that every
pending row is exactly one of live or overdue. The key method is Approve,
[`lifecycle.py:152`](../src/reservations/lifecycle.py#L152) `_decide()`: in one transaction it reloads
the row, checks that the actor is the booked companion (otherwise `403`), checks the state, and then
either the deadline has passed — it stores `EXPIRED` and returns `409 EXPIRED` — or it **checks BR-02
again** ([`:182`](../src/reservations/lifecycle.py#L182)) and only then writes `CONFIRMED`. The policy
only says whether a request can still be decided; who may decide and the status write stay in the
Lifecycle.

Sources: [Key interface and contract](architecture-and-decisions.md#key-interface-and-contract), the
sequence [Detailed sequence inside the unit](architecture-and-decisions.md#detailed-sequence-inside-the-unit)
and `_decide()` in code; see also [DD-1](architecture-and-decisions.md#dd-1--selected-architecture-unit),
[DD-4](architecture-and-decisions.md#dd-4--methods-algorithms-and-dynamic-behaviour),
[DD-5 — tests derived from the design](architecture-and-decisions.md#dd-5--unit-and-component-tests-derived-from-the-design),
[Two mismatches found, and which side won](architecture-and-decisions.md#two-mismatches-found-and-which-side-won).
The unit tests are `test_approval_policy.py` (10 tests); the most interesting
one is T-3 ([`test_approval_policy.py:40`](../src/reservations/tests/test_approval_policy.py#L40)), which
checks that the Python and SQL answers agree row by row.

What we admit: through the API alone the `409 OVERLAP` branch of Approve cannot be reached, because a
live pending request already blocks every overlapping confirmation. The second check protects against
rows written outside the Lifecycle (the admin), and its test creates the conflicting row directly in
the database. **NOT VERIFIED** — reasoned from the code, not measured. The deadline sweep has no
scheduler (it is run by hand) and the 24 h window has no external source.

## Step 4 — Verification and evidence

All cases below run with `scripts/demo_c08.sh`. Every test has its
expected result (oracle) written in the code. The positive case: two touching intervals (10–11 and
11–12) are both confirmed. The negative case: a draft that overlaps a confirmed reservation gets
`409 OVERLAP` and stays `DRAFT`. The concurrency case is a real race: two threads start at the same
moment (a barrier), send real HTTP requests to a running test server, and each request waits 0.2 s
between its BR-02 check and its write. The expected result is exactly one `200` and one
`409 OVERLAP`, and in the database one winner and one `DRAFT`
([`test_concurrency.py:76`](../src/reservations/tests/test_concurrency.py#L76), oracle at
[`:86`](../src/reservations/tests/test_concurrency.py#L86)). With `IMMEDIATE` the two transactions do
not run at the same time — the second waits for the lock — but the two requests do overlap. That this
test can fail was shown on 2026-10-21: without `IMMEDIATE` it gave `200` + `500`
([C03/C05 review fixes](evidence-and-evolution.md#c03c05-review-fixes-2026-10-21); not repeated on this
baseline).

```bash
scripts/demo_c08.sh     # (a) positive 3 · (b) negative 2 · (c) race 2 · (d) approval 12 · (e) architecture 11
```

| Case | Test | Expected | Result |
|---|---|---|---|
| plain confirm | [`test_confirm.py:18`](../src/reservations/tests/test_confirm.py#L18) | `200`, `CONFIRMED` | pass |
| touching intervals | [`test_confirm.py:110`](../src/reservations/tests/test_confirm.py#L110) | both `CONFIRMED` | pass |
| overlap with a confirmed one | [`test_confirm.py:80`](../src/reservations/tests/test_confirm.py#L80) | `409 OVERLAP`, stays `DRAFT` | pass |
| **race of two confirmations (REQ-04)** | [`test_concurrency.py:76`](../src/reservations/tests/test_concurrency.py#L76) | one `200`, one `409 OVERLAP` | 2 passed |
| approve when the slot got taken | [`test_approve.py:101`](../src/reservations/tests/test_approve.py#L101) | `409 OVERLAP`, stays `PENDING_APPROVAL` | pass |
| approve after the deadline | [`test_approve.py:76`](../src/reservations/tests/test_approve.py#L76) | `409 EXPIRED`, stored `EXPIRED` | pass |

**C04 quality criterion: N/A.** C04 did not take place for our group (public holiday), so no quality
criterion was ever set. Its role is taken by REQ-04 as a concurrency claim with the oracle above.

What we admit: REQ-04 holds only while SQLite's 5 s lock timeout is enough; a lock held longer still
ends in `500` (**NOT VERIFIED**, not tested). Approve has no parallel test — the second case of the race
test races two Confirms whose winner goes to `PENDING_APPROVAL`, not two Approves (**NOT VERIFIED**
under concurrency). The race is two requests, not a load test, and the overlap is very likely, not
guaranteed.

## Step 5 — C06 findings and our decision

Office Reservation System assessed commit `51111fa` and raised three candidates. Our rule: a finding
is a proven nonconformity with something C01–C05 required; a true observation that breaks no
requirement is a **REJECTED CANDIDATE**. **F1** (architecture rules are checked automatically) is true,
but it confirms that we conform — rejected candidate, no change. **F2** (no CI) the assessors rejected
themselves, and C06 lists it as a non-finding — reject. **F3** (dependencies may not be pinned) is the
most important one: we opened `requirements.txt` and it really has only `~=` ranges, so the
observation is true, but no C01–C05 task required a pinned environment (C01 offered it only as spike C;
we did spike A), and the assessors had not checked the file. Decision: rejected candidate, no change;
the risk of a newer minor version is accepted, we record exact versions with every result, and it goes
into part B as
[R-02](evidence-and-evolution.md#r-02--a-fresh-install-pulls-different-dependency-versions). None of
the three touched the REQ-04 / BR-02 line. The weak spot on that line, the Django admin from step 2,
we found ourselves: **DEFER**, no code change now, a Security risk for part B,
[R-01](evidence-and-evolution.md#r-01--the-django-admin-edits-reservations-around-the-lifecycle-and-br-02),
possible fix `readonly_fields` in `ReservationAdmin`.

Sources: [C06 Internal Evidence Assessment](evidence-and-evolution.md#c06-internal-evidence-assessment)
(the overview table and [F3](evidence-and-evolution.md#f3--dependencies-may-not-be-pinned)) and the
[Own observation](evidence-and-evolution.md#own-observation-not-raised-by-c06--the-django-admin-bypasses-the-lifecycle-and-br-02),
the assessors' form with our disposition in
[c06-assessment-by-office-reservation.md](c06-assessment-by-office-reservation.md#owner-disposition)
(ACCEPTED / REJECTED there means ACCEPT / REJECT here),
[F1](evidence-and-evolution.md#f1--architecture-is-validated-automatically),
[F2](evidence-and-evolution.md#f2--no-ci-pipeline).

```bash
cat requirements.txt    # F3: Django~=5.2, djangorestframework~=3.16, pytest~=8.3, pytest-django~=4.11
git diff --stat 51111fa c08-review -- src scripts/check_architecture.py requirements.txt pytest.ini   # empty
```
