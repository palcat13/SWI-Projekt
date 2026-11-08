# Technical Design Review — C07–C08, part A

A guide for the 8–10 minute technical defence of CP1. No new deck: we show the repository, the
existing Mermaid diagrams (they render on GitHub) and tests run live. One line runs through all five
steps:

> **REQ-04 + BR-02** (Confirm must not produce two overlapping `CONFIRMED` reservations) →
> **ADR-01** (the Reservation Lifecycle element owns `Reservation.status` and checks BR-02 inside the
> writing transaction; SQLite `BEGIN IMMEDIATE` serialises the race) → **C05 Approval Policy**
> (the deadline contract, one live/overdue rule in Python and in SQL, BR-02 re-checked at Approve) →
> **evidence** (touching intervals allowed, overlap refused, a real parallel race ends with exactly
> one winner) → **C06** (no candidate is a nonconformity with a C01–C05 claim, so all three are
> REJECTED CANDIDATEs; our own observation of the unprotected admin path is deferred to part B).

Every step lists **Say** (what to say), **Show** (where to point) split into **Must show** (1–3 items
we really open in the ~2 minutes of the step) and **If asked** (the rest, ready for questions), **Run**
(the command) and, where it applies, **Limits** (what we admit). Code references are `file:line` on the
reporting baseline.

## Reporting baseline

| Item | Value |
|---|---|
| **Reporting baseline** | tag **`c08-review`**, commit `<COMMIT>`, 2026-11-08 — the same baseline as part C (status report) |
| **C06 assessed baseline** | commit `51111fa` (assessed by Office Reservation System, 2026-10-22); findings are reproduced against it |
| **Old → new** | `c08-review` = `51111fa` + `093d516` (C06 record) + the C07–C08 documents and `scripts/demo_c08.sh`. `git diff --stat 51111fa c08-review -- src scripts/check_architecture.py requirements.txt pytest.ini` is expected to be empty (it is empty against HEAD `093d516`): code, tests, checker, dependencies and pytest configuration are identical to the assessed baseline. No C06 finding was fixed in code; none is a nonconformity (see [step 5](#step-5--c06-findings--engineering-decision)) |
| **Environment** | Python 3.14.7, Django 5.2.18, DRF 3.18.3, pytest 8.4.2, `.venv` from `requirements.txt` |
| **Whole suite** | `.venv/bin/python -m pytest -q` → `<PYTEST_RESULT>` (to be run on `c08-review` after tagging; 80 passed on `51111fa`) |
| **Demo** | `scripts/demo_c08.sh` → `<DEMO_RESULT>` (to be run on `c08-review` after tagging; expected: exit 0, groups (a) 3 passed · (b) 2 passed · (c) 2 passed · (d) 12 passed · (e) 11 passed + `Architecture rules hold`) |
| **SQLite settings** | `transaction_mode = "IMMEDIATE"` and `PRAGMA busy_timeout` = 5000 ms, read from a live connection (`manage.py shell`) |

**Before the defence:** run nothing else that uses pytest in this checkout. The test database is one
file, `src/test_db.sqlite3` ([`settings.py:58`](../src/config/settings.py#L58)), so two `pytest`
processes at the same time break each other — run the demo groups one after another.

## Step 1 — Scope & accepted behaviour

**Say.** Rent-a-Partner books a **companion** (a person with their own account) for a time-boxed
social activity; the actors are Customer, Companion and Administrator, and the Notification Service
is an external boundary that is not integrated. The selected operation is **OP-03 Confirm**: a `DRAFT`
becomes an allocation of the companion, and that is where the invariant **BR-02** must hold — no two
*blocking* reservations of one companion may overlap, with half-open intervals so that `[10,11)` and
`[11,12)` do not overlap (BR-01). Change **C02 (Approval)** split Confirm into a request and a
companion's decision: for `requires_approval` the request ends in `PENDING_APPROVAL`, which blocks
while its deadline is live, so REQ-04 now also covers the request step.

**Show.**

*Must show:*
- REQ-03, **REQ-04**, preconditions, success postcondition, failure outcomes, verification examples —
  including *"two overlapping drafts, confirmed at the same time → exactly one `CONFIRMED`, the other
  `409 OVERLAP` and still `DRAFT`"*: [OP-03 — Confirm Reservation](specification.md#op-03--confirm-reservation)
- BR-01, BR-02 (v0.1 vs. v0.2 blocking set), BR-04: [Domain rules and invariants](specification.md#domain-rules-and-invariants)
- Statechart with the guards of both branches out of `DRAFT`: [Reservation lifecycle (v0.2)](specification.md#reservation-lifecycle-v02)

*If asked:*
- Actors and boundary: [specification.md — Actors and system boundary](specification.md#actors-and-system-boundary)
- What C02 changed and what it left alone (REQ-04 "unchanged in meaning; it just now also applies to
  the request step"): [C02 change impact](specification.md#c02-change-impact)
- REQ-07 … REQ-10: [OP-05 — Approve Reservation](specification.md#op-05--approve-reservation-new)
- What each REQ means, and why REQ-04 is "a business outcome, not a lock": [Requirement acceptance check](specification.md#requirement-acceptance-check)

**Run.** Nothing here; the verification examples are executed in step 4.

**Limits.**
- The actor is `actor_user_id` in the request body, not authentication (BR-06 *TBD*, D6/D7). Anyone
  can claim any identity; actor rules are tested, identity is not.
- The baseline is still v0.2, but behaviour changed once inside it: C05 resolved a contradiction in
  BR-03 (an overdue pending request is `EXPIRED`, not cancellable). Tag `v0.2` (`f764c83`) still has the
  C02 behaviour — see [C05 — DD Verification Evidence](evidence-and-evolution.md#c05--dd-verification-evidence).

## Step 2 — Architecture

**Say.** AS-IS, one view did everything: the BR-02 probe and the `UPDATE` were two statements with no
lock between them, and three views reacted to the same rule. That gave drivers **DR-1** (BR-02 under
concurrency) and **DR-4** (one owner per transition). We compared **A** — an application-layer
Lifecycle element that owns `Reservation.status` and checks BR-02 inside the writing transaction —
with **B** — a PostgreSQL `ExclusionConstraint`. **ADR-01 chose A**: B can enforce only the
`CONFIRMED` half of BR-02, because a constraint condition cannot depend on `now()` and the live-pending
half does, and B would break the "runs from a clean checkout with only Python" constraint (D3). The
2026-10-21 review measured the race (on SQLite: no double booking, but the loser got `500` instead of
`409`), found the missed cheaper variant A + `BEGIN IMMEDIATE`, and recorded it as the ADR-01 addendum.

**Show.**

*Must show:*
- [E2 — the DR-2 row decides](architecture-and-decisions.md#e2--the-alternatives-against-the-drivers)
  → [ADR-01](architecture-and-decisions.md#adr-01--where-the-authoritative-confirmation-decision-is-made-and-what-enforces-br-02-under-concurrency)
  (accepted negative consequences, reconsider-when triggers) and the
  [ADR-01 addendum — IMMEDIATE](architecture-and-decisions.md#adr-01-addendum--2026-10-21-sqlite-immediate-transactions)
- Dynamic view: [H1 — sequence of Confirm](architecture-and-decisions.md#h1--design-sequence-diagram-confirm-reservation)
- [`lifecycle.py:58`](../src/reservations/lifecycle.py#L58) `confirm()` and the `check_architecture.py` run below

*If asked:*
- AS-IS: [A2 — main success path mapped to code](architecture-and-decisions.md#a2--the-main-success-path-mapped-to-code),
  [A3 — conflict → rejection](architecture-and-decisions.md#a3--one-important-failure-path-conflict--rejection)
  (with its 2026-10-21 correction), [A8 — the question carried forward](architecture-and-decisions.md#a8--one-question-to-carry-into-the-architecture-design)
- Drivers and owners: [B — drivers](architecture-and-decisions.md#b--architecture-drivers-refined),
  [C2 — responsibilities, one owner each](architecture-and-decisions.md#c2--system-responsibilities)
- Alternatives: [E1](architecture-and-decisions.md#e1--two-materially-different-alternatives)
- Static view: [G2 — TO-BE static architecture](architecture-and-decisions.md#g2--to-be-static-architecture);
  what moved: [J — AS-IS → TO-BE delta](architecture-and-decisions.md#j--as-is--to-be-delta)
- Implementation matching the decision:
  - [`settings.py:56`](../src/config/settings.py#L56) — `"transaction_mode": "IMMEDIATE"` (the addendum)
  - [`lifecycle.py:58`](../src/reservations/lifecycle.py#L58) `confirm()`: transaction opened at
    [`:66`](../src/reservations/lifecycle.py#L66), BR-02 probe at
    [`:82`](../src/reservations/lifecycle.py#L82), approval branch at
    [`:87`](../src/reservations/lifecycle.py#L87), the single write at
    [`:95`](../src/reservations/lifecycle.py#L95), notification after commit at
    [`:96`](../src/reservations/lifecycle.py#L96)
  - [`availability.py:12`](../src/reservations/availability.py#L12) `blocking_reservations()` — the
    one definition of BR-02, including the live-pending predicate from the policy at
    [`:25`](../src/reservations/availability.py#L25)
  - [`views.py:69`](../src/reservations/views.py#L69) `TransitionView` (actor, `404`, outcome → HTTP)
    and [`views.py:88`](../src/reservations/views.py#L88) `ReservationConfirmView` — one line binding
    `lifecycle.confirm`
- Conformance: [L2 — architecture conformance](architecture-and-decisions.md#l2--architecture-conformance)

**Run.**

```bash
.venv/bin/python scripts/check_architecture.py
# Architecture rules hold: Reservation.status is written only by lifecycle.py,
# and no domain module depends on the web framework.
```

**Limits.**
- **Nothing outside the application protects BR-02** (ADR-01, accepted consequence 2). This path
  really exists: the Django admin is mounted at `/admin/` and
  [`admin.py:12`](../src/reservations/admin.py#L12) `ReservationAdmin` is a plain `ModelAdmin`
  without `readonly_fields`, so its form offers `status`, `start_at`, `end_at` and `approval_deadline`
  for editing (checked 2026-11-08 with `ReservationAdmin.get_form(...).base_fields`). A staff user can
  create a double booking there, and `check_architecture.py` cannot see it, because the form writes
  through generic `ModelForm` code, not through a `.status =` in our source. **NOT VERIFIED** (no
  mitigation): recorded as our own observation, DEFER, carried into part B —
  [Own observation (not raised by C06)](evidence-and-evolution.md#own-observation-not-raised-by-c06--the-django-admin-bypasses-the-lifecycle-and-br-02).
- `transaction_mode` is SQLite-only; a move to PostgreSQL must bring `select_for_update()` or the
  constraint (addendum, *Reconsider when*). Throughput is one writer at a time.

## Step 3 — Detailed Design

**Say.** The C05 unit is the **Approval Policy** plus the approval paths of the Lifecycle. Its
interface has five operations; the contract of `deadline_for` is `now < result <= start_at`, i.e.
`min(now + window, start_at)` with two reachable branches. The rule "is this pending request still
live" is asked in Python (`is_live`) and in SQL (`live_q`, `overdue_q`), so the contract names two
postconditions — **AGREEMENT** (both answer alike) and **TOTALITY** (every pending row is exactly one of
live/overdue, a `NULL` deadline counts as overdue). The key method is Approve: inside one IMMEDIATE
transaction it reloads the row, checks the actor (BR-04) and the state, asks for the *effective*
status, and either materialises `EXPIRED` and refuses, or **re-checks BR-02** and writes `CONFIRMED`.
The boundary: the policy answers *may this still be decided*, never *who may decide it*, and only the
Lifecycle writes `status`.

**Show.**

*Must show:*
- The contract: [Key interface and contract](architecture-and-decisions.md#key-interface-and-contract)
- The approve sequence with both branches: [Detailed sequence inside the unit](architecture-and-decisions.md#detailed-sequence-inside-the-unit)
- [`lifecycle.py:152`](../src/reservations/lifecycle.py#L152) `_decide()` with the BR-02 re-check at
  [`:182`](../src/reservations/lifecycle.py#L182)

*If asked:*
- Unit and its requirements: [DD-1](architecture-and-decisions.md#dd-1--selected-architecture-unit);
  owners per responsibility and the contract: [DD-3](architecture-and-decisions.md#dd-3--design-elements-ownership-and-contracts)
- Algorithm, decision table of the effective status, significant operations:
  [DD-4](architecture-and-decisions.md#dd-4--methods-algorithms-and-dynamic-behaviour)
- Tests derived from the design (T-1 … T-9): [DD-5](architecture-and-decisions.md#dd-5--unit-and-component-tests-derived-from-the-design)
- Where code and design disagreed and the design won: [Two mismatches found, and which side won](architecture-and-decisions.md#two-mismatches-found-and-which-side-won)
- Code:
  - [`approval.py:11`](../src/reservations/approval.py#L11) `ApprovalPolicy` (ABC);
    [`approval.py:40`](../src/reservations/approval.py#L40) `deadline_for` → `min(now + self.window, start_at)` at
    [`:41`](../src/reservations/approval.py#L41); [`:43`](../src/reservations/approval.py#L43) `is_live`,
    [`:50`](../src/reservations/approval.py#L50) `live_q` (non-null and future deadline),
    [`:57`](../src/reservations/approval.py#L57) `overdue_q` (null *or* past);
    [`:77`](../src/reservations/approval.py#L77) `effective_status()`
  - [`lifecycle.py:152`](../src/reservations/lifecycle.py#L152) `_decide()` (behind
    [`approve()`](../src/reservations/lifecycle.py#L198)): transaction at
    [`:162`](../src/reservations/lifecycle.py#L162); actor → `403 FORBIDDEN_ACTOR` at
    [`:164`](../src/reservations/lifecycle.py#L164); state → `409 INVALID_STATE` at
    [`:170`](../src/reservations/lifecycle.py#L170); effective status `EXPIRED` → stored `EXPIRED`,
    then `409 EXPIRED` at [`:177`](../src/reservations/lifecycle.py#L177); **BR-02 re-check** →
    `409 OVERLAP`, stays `PENDING_APPROVAL` at [`:182`](../src/reservations/lifecycle.py#L182); write
    `CONFIRMED` + `decided_by` at [`:188`](../src/reservations/lifecycle.py#L188)
  - [`lifecycle.py:216`](../src/reservations/lifecycle.py#L216) `reconcile_overdue_approvals()` — the
    sweeper's write, with the predicate supplied by the policy

**Run.**

```bash
.venv/bin/python -m pytest -v src/reservations/tests/test_approval_policy.py   # T-1 … T-9 + T-7b: 10 passed
```

Worth opening: T-3 ([`test_approval_policy.py:40`](../src/reservations/tests/test_approval_policy.py#L40),
AGREEMENT row by row against the real SQL) and T-4 ([`:61`](../src/reservations/tests/test_approval_policy.py#L61),
TOTALITY — fails against the pre-C05 predicates).

**Limits.**
- Through the API alone, the `409 OVERLAP` branch of Approve is not reachable: a live pending request
  already blocks every overlapping confirmation, and once its deadline passes Approve answers
  `EXPIRED`. The re-check guards against rows written outside the Lifecycle (the admin form, step 2);
  its test creates the conflicting row directly through the ORM. **NOT VERIFIED** *(reasoned from
  the code, not measured).*
- No scheduler runs the sweep (DR-2 half closed); `set_policy()` is process-global; the 24 h window has
  no external source — [C05 remaining design risk](evidence-and-evolution.md#c05--dd-verification-evidence).

## Step 4 — Verification & Evidence

**Say.** Each case has an explicit oracle written in the test, and all of them pass on the reporting
baseline (the run is recorded in [Reporting baseline](#reporting-baseline)). The concurrency case is a
real race: two threads released by a barrier send real HTTP requests to a live server, and each request
is held 0.2 s between its BR-02 probe and its write. With `BEGIN IMMEDIATE` the two transactions do not
overlap — the second waits for the write lock — but the two *requests* do; the barrier plus the 0.2 s
hold makes that overlap highly likely, not guaranteed. Without `IMMEDIATE` the same test gives `200` +
`500` — that is the evidence that the test can fail.

**Show.**

*Must show:*
- `scripts/demo_c08.sh` running (Run below), with
  [`test_concurrency.py:76`](../src/reservations/tests/test_concurrency.py#L76) open beside it — the
  oracle at [`:86`](../src/reservations/tests/test_concurrency.py#L86)
- The concurrency row of the table below

*If asked:* the other rows of the table, the conditions of the concurrency measurement and the C04 N/A
below.

| Case | Test | Expected (oracle) | Observed (run on `c08-review`, see Reporting baseline) |
|---|---|---|---|
| positive — plain confirm | [`test_confirm.py:18`](../src/reservations/tests/test_confirm.py#L18) | `200`, `CONFIRMED` | pass |
| positive / boundary — touching intervals `[s, s+1h)`, `[s+1h, s+2h)` | [`test_confirm.py:110`](../src/reservations/tests/test_confirm.py#L110), [`test_availability.py:45`](../src/reservations/tests/test_availability.py#L45) | both `CONFIRMED`; the neighbouring intervals are `available: true` (BR-01) | pass |
| negative — overlap with a `CONFIRMED` | [`test_confirm.py:80`](../src/reservations/tests/test_confirm.py#L80) | `409 OVERLAP`, the draft stays `DRAFT` | pass |
| negative — two conflicting confirmations in sequence | [`test_confirm.py:94`](../src/reservations/tests/test_confirm.py#L94) | first `CONFIRMED`, second `409 OVERLAP` | pass |
| **concurrency — REQ-04**, two cases: direct companion, and a companion requiring approval (the winner ends in `PENDING_APPROVAL`) | [`test_concurrency.py:76`](../src/reservations/tests/test_concurrency.py#L76) | responses sorted = `[(200, None), (409, "OVERLAP")]` ([`:86`](../src/reservations/tests/test_concurrency.py#L86)); stored = {winner state, `DRAFT`} | 2 passed |
| approval — slot taken meanwhile (REQ-09 re-check) | [`test_approve.py:101`](../src/reservations/tests/test_approve.py#L101) | `409 OVERLAP`, stays `PENDING_APPROVAL` | pass |
| approval — 1 s after the deadline (REQ-10) | [`test_approve.py:76`](../src/reservations/tests/test_approve.py#L76) | `409 EXPIRED`, stored `EXPIRED` | pass |

**Conditions of the concurrency measurement:** a live server over real HTTP — Django's in-process
test client re-raises one thread's `500` in the other, see the
[addendum](architecture-and-decisions.md#adr-01-addendum--2026-10-21-sqlite-immediate-transactions);
`threading.Barrier` at [`test_concurrency.py:40`](../src/reservations/tests/test_concurrency.py#L40);
the hold `RACE_WINDOW = 0.2` s at [`:16`](../src/reservations/tests/test_concurrency.py#L16), applied
by the `slow_probe` fixture at [`:59`](../src/reservations/tests/test_concurrency.py#L59); a file test
database ([`settings.py:58`](../src/config/settings.py#L58)), because the default shared-cache
in-memory database fails with `database table is locked`; `IMMEDIATE`
([`settings.py:56`](../src/config/settings.py#L56)); busy timeout 5000 ms. The control runs (without
`IMMEDIATE` → `[200, 500]`; in-memory DB → `table is locked`) are recorded in
[C03/C05 review fixes](evidence-and-evolution.md#c03c05-review-fixes-2026-10-21) (2026-10-21) and were
not repeated on this baseline.

**C04 quality criterion: N/A.** C04 did not take place for our seminar group (public holiday), so no
quality concern, criterion or measurement was ever set. The C06 assessors answered Q1–Q3 YES for a
concern they picked themselves; our answer is N/A
([C06 — Actions / no-change](evidence-and-evolution.md#c06-internal-evidence-assessment)). The role a
quality criterion would play is taken by **REQ-04 as a concurrency claim**: the oracle is line 86–88
of `test_concurrency.py`, under the conditions above.

**Run.**

```bash
scripts/demo_c08.sh                 # (a)–(e) in order; nothing else running pytest meanwhile
.venv/bin/python -m pytest -q       # the whole suite: <PYTEST_RESULT> (80 passed on 51111fa)
```

Expected output of the demo: (a) positive 3 passed · (b) negative 2 passed · (c) concurrency 2 passed ·
(d) approval 12 passed (two approve tests + the ten C05 tests) · (e) `test_architecture.py` 11 passed
and `Architecture rules hold`.

**Limits.**
- REQ-04 holds within SQLite's 5 s busy timeout. A write lock held longer still ends in `500`
  (`OperationalError: database is locked`). **NOT VERIFIED** — not tested.
- **The Approve path has no parallel test.** Its BR-02 re-check runs in the same kind of IMMEDIATE
  transaction, so it is serialised the same way, but nothing races an Approve. The
  `approval_companion-PENDING_APPROVAL` case of `test_concurrency.py` races two **Confirm** requests
  whose winner ends in `PENDING_APPROVAL`; it is not a race of Approve. **NOT VERIFIED** under
  concurrency (reasoned from the code, not measured).
- The race test covers two requests and one 0.2 s window; it is not a load test. The overlap of the two
  requests is made highly likely by the barrier and the hold, not guaranteed.
- Tests share `src/test_db.sqlite3`, so two pytest processes in one checkout break each other.

## Step 5 — C06 Findings & Engineering Decision

**Say.** Our criterion: a **VERIFIED FINDING** is a reproduced nonconformity with a C01–C05 claim on
`51111fa` (the assignment defines a finding as "a proven nonconformity with an accepted claim");
anything else is a **REJECTED CANDIDATE**. Office Reservation System assessed `51111fa` and raised
three candidates: **F1** (architecture is validated automatically — true, but it confirms conformance,
so REJECTED CANDIDATE; ACCEPT observation, no change), **F2** (no CI — they rejected it themselves, and
the C06 assignment lists it among non-findings: REJECT) and **F3** (dependencies may not be pinned).
The assessors marked F1 and F3 VERIFIED because the observations are true; we differ because neither
contradicts a C01–C05 claim. F3 is the most important one, because it is the only VERIFIED one that
could be a defect. We verified it technically: `requirements.txt` has only compatible-release `~=`
constraints, so the observation is true — but no C01–C05 claim requires a reproducible environment
(C01 offered it only as spike C, we chose spike A), and the assessors had not opened the file.
Decision: **REJECTED CANDIDATE, REJECT, no change**; the residual risk of a newer minor version is
accepted, mitigated only by recording the versions with every result, and carried into part B (risk
register, not yet written) — risk ID `[doplnit]`. None of the candidates touched the REQ-04 / BR-02
line. The one unprotected path on that line, the Django admin (step 2), is our own observation, not a
C06 finding: **DEFER**, no code change at the reporting baseline, carried into part B as a Security /
Privacy risk — risk ID `[doplnit]`; candidate action `readonly_fields` in `ReservationAdmin`; status
**NOT VERIFIED** (no mitigation).

**Show.**

*Must show:*
- The overview table with the criterion above it, then
  [F3](evidence-and-evolution.md#f3--dependencies-may-not-be-pinned) and `cat requirements.txt` (Run
  below): [C06 Internal Evidence Assessment](evidence-and-evolution.md#c06-internal-evidence-assessment)
- The admin path and its action:
  [Own observation (not raised by C06)](evidence-and-evolution.md#own-observation-not-raised-by-c06--the-django-admin-bypasses-the-lifecycle-and-br-02)

*If asked:*
- Their form, unchanged, with our owner disposition: [Candidate findings](c06-assessment-by-office-reservation.md#candidate-findings),
  [Owner disposition](c06-assessment-by-office-reservation.md#owner-disposition), and their C04 answers:
  [C04 — Quality & Measurement](c06-assessment-by-office-reservation.md#c04--quality--measurement).
  ACCEPTED / REJECTED in that form means ACCEPT / REJECT here; for F1 the reclassification to
  REJECTED CANDIDATE does not change its "no change" decision.
- Claim → expected → observed → verify → disposition → closure for the other two:
  [F1](evidence-and-evolution.md#f1--architecture-is-validated-automatically),
  [F2](evidence-and-evolution.md#f2--no-ci-pipeline)
- Old → new: no C06 finding was fixed in code; none is a nonconformity. The closure link is therefore
  the empty diff of code, tests, checker, dependencies and pytest configuration
  (`git diff --stat 51111fa c08-review -- …`, Run below).

**Run.**

```bash
cat requirements.txt                                   # F3: Django~=5.2, djangorestframework~=3.16, pytest~=8.3, pytest-django~=4.11
ls .github .gitlab-ci.yml                              # F2: both "No such file or directory"
.venv/bin/python scripts/check_architecture.py         # F1: Architecture rules hold
.venv/bin/python -m pytest -q src/reservations/tests/test_architecture.py   # F1: 11 passed
git diff --stat 51111fa c08-review -- src scripts/check_architecture.py requirements.txt pytest.ini
                                                       # empty: identical to the assessed baseline
```

**Limits.**
- Most YES answers in the assessment rest on the presence of files, not on an inspected code path or a
  run; we do not count them as extra verification.
- Open items we carry ourselves, none raised by the assessment — the
  [remaining evidence gaps](evidence-and-evolution.md#c06-internal-evidence-assessment): the 5 s
  busy-timeout limit (**NOT VERIFIED**, not tested), no parallel test of Approve (**NOT VERIFIED**,
  reasoned from the code, not measured), the checker's blind spots (`Reservation(status=…)` +
  `save()`, `bulk_create`, `update(**{"status": …})`), the notification stub, no expiry scheduler,
  `actor_user_id` instead of authentication; plus ADR-01's accepted consequence 2, the admin form that
  bypasses BR-02 (step 2; **NOT VERIFIED**, no mitigation —
  [own observation](evidence-and-evolution.md#own-observation-not-raised-by-c06--the-django-admin-bypasses-the-lifecycle-and-br-02)).

## Time plan

| Min | Step | Screen |
|---|---|---|
| 0:00–2:00 | 1 Scope & accepted behaviour | `specification.md`: OP-03, BR-02, the v0.2 statechart |
| 2:00–4:00 | 2 Architecture | A3 → E2 → ADR-01 + addendum → G2 / H1 → `lifecycle.py:58`; run `check_architecture.py` |
| 4:00–6:00 | 3 Detailed Design | DD-3 contract → DD-4 sequence → `lifecycle.py:152` |
| 6:00–8:30 | 4 Verification & Evidence | `scripts/demo_c08.sh` running; `test_concurrency.py:76` open beside it |
| 8:30–10:00 | 5 C06 findings & decision | the C06 section of `evidence-and-evolution.md`; `cat requirements.txt` |

Start the demo at the beginning of step 4 so it runs while we talk; it needs no server of its own
(pytest-django starts the live server for the race test).

## Likely questions

**Why not a PostgreSQL `ExclusionConstraint`?** A constraint condition must be immutable, and the
pending half of BR-02 depends on `now()` (blocking *until the deadline*). B would enforce only the
`CONFIRMED` half and leave the rule in two homes, and it would require PostgreSQL for every test run.
It becomes nearly free if we move to PostgreSQL for another reason — that is one of ADR-01's
reconsider-when triggers. → [E2](architecture-and-decisions.md#e2--the-alternatives-against-the-drivers),
[ADR-01](architecture-and-decisions.md#adr-01--where-the-authoritative-confirmation-decision-is-made-and-what-enforces-br-02-under-concurrency)

**Why `IMMEDIATE`, and what does it change?** With the default deferred transaction both requests
read "free" under a shared lock, and the one that cannot upgrade to a write lock fails with `database
is locked` → `500`. `BEGIN IMMEDIATE` takes the write lock before the first statement, so the second
confirmation waits, starts after the first commit, and its BR-02 probe sees the winner → `409
OVERLAP`. → [addendum](architecture-and-decisions.md#adr-01-addendum--2026-10-21-sqlite-immediate-transactions),
[`settings.py:56`](../src/config/settings.py#L56)

**What if the lock is held longer than 5 s?** The waiting request gets `OperationalError: database is
locked`, which the API does not catch, so its client sees `500`. Nothing is written by the failed
request, so BR-02 still holds, but REQ-04's promised `409 OVERLAP` does not. It is a known, untested
limit, listed in the
[remaining evidence gaps](evidence-and-evolution.md#c06-internal-evidence-assessment).

**Why a 24 h approval window?** It comes from the C01 assumption "companions respond within 24 h" and
has no external source; the specification says so. C05 made it a variation point
(`FixedWindowApprovalPolicy(window)`, T-9), so changing it is one argument, not a code change. →
[Requirement acceptance check — Uncertainty](specification.md#requirement-acceptance-check),
[DD-3](architecture-and-decisions.md#dd-3--design-elements-ownership-and-contracts)

**How do you know nothing else writes `status`?** For our own source: `check_architecture.py` scans the
AST for attribute writes, `setattr`, `update`/`bulk_update`, `create`-family calls with `status`, and
its tests include synthetic violations, so it cannot pass vacuously; on the pre-refactor commit
`f764c83` it reports all six old writes. It does **not** see `Reservation(status=…)` + `save()`,
`bulk_create`, `update(**{"status": …})`, and it cannot see the Django admin form, which can edit
`status` — that is ADR-01's accepted consequence 2. →
[L2](architecture-and-decisions.md#l2--architecture-conformance)

**Why are F1 and F3 REJECTED CANDIDATEs when the assessors marked them VERIFIED and both are true?**
A finding is a proven nonconformity with an accepted claim; being true is not enough. F1 confirms
conformance (ACCEPT observation, no change). For F3: C06 judges the obligations of C01–C05, and none of
them claims a reproducible, pinned environment; C01 offered that only as spike C, and we did spike A.
The observation is recorded as true, the residual risk is accepted, carried into part B, and exact
versions are written next to every result. →
[F1](evidence-and-evolution.md#f1--architecture-is-validated-automatically),
[F3](evidence-and-evolution.md#f3--dependencies-may-not-be-pinned)

**What do you do about the admin path?** Nothing in code at the reporting baseline: it is our own
observation, not a C06 finding, deferred into part B as a Security / Privacy risk. Trigger: any real
admin/staff user or any data edited via `/admin/`; candidate action: `readonly_fields` for `status`,
`start_at`, `end_at`, `approval_deadline`. NOT VERIFIED — no mitigation exists. →
[Own observation](evidence-and-evolution.md#own-observation-not-raised-by-c06--the-django-admin-bypasses-the-lifecycle-and-br-02)

**Why does Approve re-check BR-02 if the pending request already blocks the slot?** Because "nothing
else wrote an overlapping row" is not guaranteed — the admin form can. Through the API alone the
branch is unreachable; the re-check makes Approve safe without relying on that. →
[`lifecycle.py:182`](../src/reservations/lifecycle.py#L182),
[`test_approve.py:101`](../src/reservations/tests/test_approve.py#L101)

**How do you know the race test really races?** The barrier releases both threads together and the
0.2 s hold sits between each probe and its write, so the two *requests* overlap with high probability,
though not with a guarantee (thread scheduling could still separate them). With `IMMEDIATE` the two
transactions themselves do not overlap: the second waits for the write lock. The evidence that the
requests do race is that the same test without `IMMEDIATE` fails with `[200, 500]`, and on the in-memory
test database with `table is locked`. It uses a live server because the in-process test client would mix the two threads'
exceptions. → [C03/C05 review fixes](evidence-and-evolution.md#c03c05-review-fixes-2026-10-21)
