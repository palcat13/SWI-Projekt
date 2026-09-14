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

## Persistent state
**Reservation:** `id` (UUID), `companion` (FK → Companion), `customer` (FK → User), `start_at`, `end_at` (timezone-aware, stored in UTC), `activity` (`DINNER` / `EVENT` / `WALK` / `OTHER`), `status` (`DRAFT` / `PENDING_APPROVAL` / `CONFIRMED` / `CANCELLED`), `created_at`, `updated_at`.

**Companion (Resource):** `id`, `user` (1:1 → User), `display_name`, `bio`, `is_active`, `created_at`.

**User:** Django `auth.User` (username, e-mail, password hash, …).

Storage: SQLite through the Django ORM + migrations (see `docs/architecture-and-decisions.md`, D3).

## State-changing operation
Reservation states: `DRAFT`, `PENDING_APPROVAL`, `CONFIRMED`, `CANCELLED`.

| Transition | Triggered by | Condition |
|---|---|---|
| `DRAFT → PENDING_APPROVAL` | Customer submits the reservation | Reservation data is valid |
| `PENDING_APPROVAL → CONFIRMED` | Companion approves the reservation | Approval comes from the booked companion; no overlap with another confirmed reservation of the same companion |
| `DRAFT / PENDING_APPROVAL / CONFIRMED → CANCELLED` | Customer or companion cancels | — |

## Common business rule
Confirmed reservations for the same resource must not overlap.

## Domain-specific business rule
A reservation can move to CONFIRMED only after the booked companion explicitly approves it. Neither the customer nor the system can confirm a reservation on the companion's behalf.

## External / system boundary
**Notification Service** — notifies the companion that a new reservation is waiting for approval, and notifies the customer when a reservation is confirmed or cancelled. The reservation system calls it; a failure or timeout of the notification must not roll back the change of the reservation's state. Not implemented in CP1; will be accessed through an interface so it can be stubbed.

## Assumption
Companions respond to a pending reservation within 24 hours.

## Unknown
What should happen to a `PENDING_APPROVAL` reservation when the companion never responds — should it expire automatically, and after how long?

# Selected future pressure

Category: C (Changeability)

Concrete pressure: Pending reservations that the companion does not approve within 24 h must expire automatically (new state `EXPIRED`).

Why it is relevant to our reservation system: The approval step is the core of our domain. A new state affects the state machine, the availability check and the notifications.
