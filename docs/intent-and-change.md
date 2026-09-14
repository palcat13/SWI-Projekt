# Project Frame

## Reservation domain
Booking a companion for a time-boxed social activity (non-sexual companionship).

## Purpose
TODO — 2–3 sentences: who the system serves and why.

## Users / Stakeholders
TODO — 1–3 roles.

## Core concepts
- **Reservation** — TODO
- **Resource (Companion)** — TODO
- **User (Customer)** — TODO

## Core operations
- Create reservation
- Confirm / approve reservation
- Cancel reservation
- Check availability

## Persistent state
TODO — what is stored about Reservation and Resource.

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
TODO — default: Notification Service.

## Assumption
TODO

## Unknown
TODO

# Selected future pressure

Category: TODO (Q / C / R / L)
Concrete pressure: TODO
Why it is relevant to our reservation system: TODO
