# Rent-a-Partner

Reservation system for booking a companion for social activities (non-sexual companionship, modeled after rental-companion services such as "rent-a-girlfriend").

## Team

- **Team name:** Rent-a-Partner
- **Members:** Pavel Marszalek, Tobias Janča
- **Repository:** https://github.com/palcat13/SWI-Projekt

## Documentation

- [Intent and change (Project Frame)](docs/intent-and-change.md)
- [Specification — baseline v0.2](docs/specification.md)
- [Architecture and decisions](docs/architecture-and-decisions.md)
- [Evidence and evolution](docs/evidence-and-evolution.md)

## Tech stack

Python 3.10+ · Django 5.2 LTS · Django REST Framework · SQLite · pytest + pytest-django.
Justification: [architecture-and-decisions.md](docs/architecture-and-decisions.md).

## Project layout

```
requirements.txt        Python dependencies
pytest.ini              pytest config (settings module, src/ on path)
src/manage.py           Django entry point
src/config/             project settings and root URLs
src/reservations/       domain app: models, serializer, API view, tests
```

## Build & run

Requires Python 3.10+ with `venv` (`sudo apt install python3-venv` on Ubuntu/Debian).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cd src
python manage.py migrate          # creates src/db.sqlite3
python manage.py runserver        # http://127.0.0.1:8000
```

Run the tests (from the repository root, venv active):

```bash
pytest
```

Create demo data and a reservation:

```bash
cd src
python manage.py shell -c "
from django.contrib.auth.models import User
from reservations.models import Companion
customer, _ = User.objects.get_or_create(username='demo-customer')
companion_user, _ = User.objects.get_or_create(username='demo-companion')
companion, _ = Companion.objects.get_or_create(user=companion_user, defaults={'display_name': 'Alice'})
print('companion_id', companion.pk, 'customer_id', customer.pk)
"

curl -X POST http://127.0.0.1:8000/reservations \
  -H 'Content-Type: application/json' \
  -d '{"companion_id": 1, "customer_id": 1, "start_at": "2027-10-01T18:00:00+02:00", "end_at": "2027-10-01T20:00:00+02:00", "activity": "DINNER"}'
# → 201 {"id": "<uuid>", "status": "DRAFT"}
```

Admin UI: `python manage.py createsuperuser`, then http://127.0.0.1:8000/admin/.

## API — baseline v0.2

| Operation | Endpoint | Body / query |
|---|---|---|
| OP-01 Create | `POST /reservations` | `companion_id`, `customer_id`, `start_at`, `end_at`, `activity` |
| OP-02 Check availability | `GET /companions/{id}/availability` | `start_at`, `end_at` (URL-encoded ISO-8601) |
| OP-03 Confirm | `POST /reservations/{uuid}/confirm` | `actor_user_id` (the customer) |
| OP-04 Cancel | `POST /reservations/{uuid}/cancel` | `actor_user_id` (the customer or the companion) |
| OP-05 Approve | `POST /reservations/{uuid}/approve` | `actor_user_id` (the booked companion) |
| OP-06 Reject | `POST /reservations/{uuid}/reject` | `actor_user_id` (the booked companion) |

Failures return `400` (invalid input), `403 FORBIDDEN_ACTOR`, `404` (unknown) or `409` with a code
(`INVALID_STATE`, `OVERLAP`, `INACTIVE_RESOURCE`, `PAST_INTERVAL`, `TOO_LATE`, `EXPIRED`).
The behaviour of every operation, including boundaries, is specified in [docs/specification.md](docs/specification.md).

Reservations awaiting approval stop blocking the companion at their deadline; the state is written by:

```bash
cd src && python manage.py expire_pending_approvals   # prints expired=<n>
```

## Demo of all operations

```bash
scripts/demo_c02.sh      # from the repository root, with the venv installed
```

The script migrates, seeds demo data, starts a server on port 8765 and runs one successful and one
negative example of every operation. The recorded output is in
[docs/evidence-and-evolution.md](docs/evidence-and-evolution.md).

## CP1 walking skeleton

```
POST /reservations
→ validate
→ persist
→ return reservation ID
→ automated check
```

| Step | Concretely |
|---|---|
| **Request** | `POST /reservations`, JSON body `{"companion_id": int, "customer_id": int, "start_at": ISO-8601 datetime, "end_at": ISO-8601 datetime, "activity": "DINNER" \| "EVENT" \| "WALK" \| "OTHER"}` |
| **Validate** | `ReservationCreateSerializer` (`src/reservations/serializers.py`): all fields required; companion exists and `is_active`; customer (user) exists; `activity` is one of the allowed values; `start_at < end_at`; `start_at` in the future; a companion cannot book themselves. Failure → `400` with per-field errors. |
| **Persist** | `Reservation` row in SQLite (`src/db.sqlite3`) with status `DRAFT`, times stored in UTC. The DB also enforces `start_at < end_at` via a check constraint. |
| **Return ID** | `201 Created`, body `{"id": "<uuid>", "status": "DRAFT"}` |
| **Automated check** | `pytest` → `src/reservations/tests/test_cp1_create_reservation.py` (happy path verifies the row exists in the DB; negative cases for every validation rule) |

Status: implemented and passing. Authentication is not part of CP1 (`customer_id` is sent in the body, see decision D6).
