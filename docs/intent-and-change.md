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
- **Reservation** — booking of one companion by one customer for a time slot; has a state.
- **Resource (Companion)** — a person offering companionship who can be booked.
- **User (Customer)** — a registered person who creates reservations.
- **Activity** — type of occasion (dinner, event, walk).

## Core operations
- Create reservation
- Confirm / approve reservation
- Cancel reservation
- Check availability

## Persistent state
- **Reservation:** id, companion_id, customer_id, start_time, end_time, activity, state, created_at, updated_at
- **Companion:** id, display_name, active

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
**Notification Service** — notifies the companion when a reservation is waiting for approval, and the customer when it is confirmed or cancelled.

## Assumption
Companions respond to a pending reservation within 24 hours.

## Unknown
What should happen to a `PENDING_APPROVAL` reservation when the companion never responds — should it expire automatically, and after how long?

# Selected future pressure

Category: C (Changeability)

Concrete pressure: Pending reservations that the companion does not approve within 24 h must expire automatically (new state `EXPIRED`).

Why it is relevant to our reservation system: The approval step is the core of our domain. A new state affects the state machine, the availability check and the notifications.
