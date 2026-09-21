# Project Frame

## Reservation domain
Booking a companion for a time-boxed social activity (non-sexual companionship).

## Purpose
The system lets customers book a companion for a time-boxed social activity such as a dinner, a wedding or a cultural event. Companions keep control over their time by approving each booking. The system prevents double-booking of a companion.

## Users / Stakeholders
- **Customer** — creates and cancels reservations.
- **Companion** — approves or cancels reservations of their own time.
- **Administrator** — manages companion profiles.

## Core concepts
- **Reservation** — a request to spend a specific time slot (`start_at`–`end_at`) with one companion; it has an identity (UUID), a state and an owner (customer).
- **Resource (Companion)** — a person offering their time; has their own user account (so they can approve reservations) and can be active or inactive.
- **User (Customer)** — a registered user who creates reservations.
- **Activity** — type of occasion the reservation is for (dinner, event, walk, other).

## Core operations
- Create reservation
- Confirm / approve reservation
- Cancel reservation
- Check availability

The full behaviour of every operation is specified in [specification.md](specification.md) (baseline v0.2).

## Persistent state
**Reservation:** `id` (UUID), `companion` (FK → Companion), `customer` (FK → User), `start_at`, `end_at` (timezone-aware, stored in UTC), `activity` (`DINNER` / `EVENT` / `WALK` / `OTHER`), `status` (`DRAFT` / `PENDING_APPROVAL` / `CONFIRMED` / `CANCELLED` / `REJECTED` / `EXPIRED`), `approval_requested_at`, `approval_deadline`, `decided_by` (FK → User), `created_at`, `updated_at`.

**Companion (Resource):** `id`, `user` (1:1 → User), `display_name`, `bio`, `is_active`, `requires_approval`, `created_at`.

**User:** Django `auth.User` (username, e-mail, password hash, …).

Storage: SQLite through the Django ORM + migrations (see `docs/architecture-and-decisions.md`, D3).

## State-changing operation
Reservation states: `DRAFT`, `PENDING_APPROVAL`, `CONFIRMED`, `CANCELLED`, `REJECTED`, `EXPIRED`.
The transitions below are the state diagram of baseline v0.2; the guards and the operations behind them are in [specification.md](specification.md).

| Transition | Triggered by | Condition |
|---|---|---|
| `[initial] → DRAFT` | Customer creates the reservation | Valid data, existing active companion |
| `DRAFT → CONFIRMED` | Customer confirms | The companion does not require approval; no overlap with a blocking reservation |
| `DRAFT → PENDING_APPROVAL` | Customer confirms | The companion requires approval; deadline = min(now + 24 h, start) |
| `PENDING_APPROVAL → CONFIRMED` | Companion approves | The booked companion, before the deadline, still no overlap |
| `PENDING_APPROVAL → REJECTED` | Companion rejects | The booked companion, before the deadline |
| `PENDING_APPROVAL → EXPIRED` | Passage of time | The approval deadline passed without a decision |
| `DRAFT / PENDING_APPROVAL → CANCELLED` | Customer or companion cancels | Before the start |
| `CONFIRMED → CANCELLED` | Customer or companion cancels | At least 24 h before the start |

## Common business rule
Reservations that block the same companion must not overlap. In baseline v0.1 only `CONFIRMED` blocks; baseline v0.2 adds `PENDING_APPROVAL` while its approval deadline is live (BR-02 in [specification.md](specification.md)).

## Domain-specific business rule
A reservation can move to CONFIRMED only after the booked companion explicitly approves it. Neither the customer nor the system can confirm a reservation on the companion's behalf.

Scope in v0.2: the rule applies to companions with `requires_approval = true`. Baseline v0.1 deliberately had the rule relaxed (direct confirmation) and change C02 brought it back — see *C02 change impact* in [specification.md](specification.md).

## External / system boundary
**Notification Service** — notifies the companion that a new reservation is waiting for approval, and notifies the customer when a reservation is confirmed or cancelled. The reservation system calls it; a failure or timeout of the notification must not roll back the change of the reservation's state. Not implemented in CP1; will be accessed through an interface so it can be stubbed.

## Assumption
Companions respond to a pending reservation within 24 hours.

## Unknown
What should happen to a `PENDING_APPROVAL` reservation when the companion never responds — should it expire automatically, and after how long?

Decided in v0.2 (C02): it expires at `min(request + 24 h, start)` and stops blocking the companion. The 24 h comes from the assumption above; it has no external source and is the first value to revisit with real data.

# Selected future pressure

Category: C (Changeability)

Concrete pressure: Pending reservations that the companion does not approve within 24 h must expire automatically (new state `EXPIRED`).

Why it is relevant to our reservation system: The approval step is the core of our domain. A new state affects the state machine, the availability check and the notifications.
