#!/usr/bin/env bash
# C02 demo: runs one successful and one negative example of every operation
# against a live server. Usage: scripts/demo_c02.sh   (from the repository root)
set -euo pipefail

PY="$PWD/.venv/bin/python"
PORT="${PORT:-8765}"
BASE="http://127.0.0.1:$PORT"
cd src

echo "== apply migrations =="
"$PY" manage.py migrate --no-input | tail -1

echo "== seed demo data =="
SEED=$("$PY" manage.py shell --no-imports -c "
from datetime import timedelta
from django.contrib.auth.models import User
from django.utils import timezone
from reservations.models import Activity, Companion, Reservation, ReservationStatus

Reservation.objects.filter(customer__username__startswith='demo-').delete()
Companion.objects.filter(user__username__startswith='demo-').delete()
User.objects.filter(username__startswith='demo-').delete()

customer = User.objects.create_user(username='demo-customer')
alice = Companion.objects.create(
    user=User.objects.create_user(username='demo-alice'), display_name='Alice')
bea = Companion.objects.create(
    user=User.objects.create_user(username='demo-bea'), display_name='Bea', requires_approval=True)

def make(companion, start, hours=2, **kwargs):
    return Reservation.objects.create(companion=companion, customer=customer, start_at=start,
                                      end_at=start + timedelta(hours=hours),
                                      activity=Activity.DINNER, **kwargs)

week = timezone.now() + timedelta(days=7)
r_confirm = make(alice, week)
r_overlap = make(alice, week + timedelta(hours=1))
r_late = make(alice, timezone.now() + timedelta(hours=12), status=ReservationStatus.CONFIRMED)
r_approve = make(bea, week + timedelta(days=1))
r_stale = make(bea, week + timedelta(days=2), status=ReservationStatus.PENDING_APPROVAL,
               approval_deadline=timezone.now() - timedelta(minutes=1))
r_reject = make(bea, week + timedelta(days=3), status=ReservationStatus.PENDING_APPROVAL,
                approval_deadline=timezone.now() + timedelta(hours=1))

print(f'CUSTOMER={customer.pk}')
print(f'ALICE={alice.pk}')
print(f'BEA={bea.pk}')
print(f'BEA_USER={bea.user_id}')
print(f'R_CONFIRM={r_confirm.id}')
print(f'R_OVERLAP={r_overlap.id}')
print(f'R_LATE={r_late.id}')
print(f'R_APPROVE={r_approve.id}')
print(f'R_REJECT={r_reject.id}')
print(f'SLOT_START={week.isoformat()}')
print(f'SLOT_END={(week + timedelta(hours=2)).isoformat()}')
")
eval "$SEED"
echo "$SEED"

"$PY" manage.py runserver "127.0.0.1:$PORT" --noreload > /tmp/demo-c02-server.log 2>&1 &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
for _ in $(seq 1 40); do curl -s -o /dev/null "$BASE/reservations" && break; sleep 0.5; done

show() { printf '\n--- %s\n' "$1"; shift; "$@"; }
post() { curl -s -w '\nHTTP %{http_code}\n' -X POST "$1" -H 'Content-Type: application/json' -d "$2"; }
get() { curl -s -w '\nHTTP %{http_code}\n' "$1"; }
# the ISO timestamps carry a "+" offset, so they must be URL-encoded
avail() { curl -s -w '\nHTTP %{http_code}\n' --get "$BASE/companions/$1/availability" \
  --data-urlencode "start_at=$2" --data-urlencode "end_at=$3"; }
actor() { printf '{"actor_user_id": %s}' "$1"; }

echo "===== OP-01 Create Reservation ====="
show "success: new DRAFT" post "$BASE/reservations" \
  "{\"companion_id\": $ALICE, \"customer_id\": $CUSTOMER, \"start_at\": \"$SLOT_START\", \"end_at\": \"$SLOT_END\", \"activity\": \"DINNER\"}"
show "negative: end_at before start_at" post "$BASE/reservations" \
  "{\"companion_id\": $ALICE, \"customer_id\": $CUSTOMER, \"start_at\": \"$SLOT_END\", \"end_at\": \"$SLOT_START\", \"activity\": \"DINNER\"}"

echo "===== OP-02 Check Availability ====="
show "success: free slot (only DRAFTs so far)" avail "$ALICE" "$SLOT_START" "$SLOT_END"
show "negative: invalid interval" avail "$ALICE" "$SLOT_END" "$SLOT_START"

echo "===== OP-03 Confirm Reservation ====="
show "success: DRAFT -> CONFIRMED" post "$BASE/reservations/$R_CONFIRM/confirm" "$(actor $CUSTOMER)"
show "boundary: the slot is now unavailable" avail "$ALICE" "$SLOT_START" "$SLOT_END"
show "negative: overlapping confirmation" post "$BASE/reservations/$R_OVERLAP/confirm" "$(actor $CUSTOMER)"

echo "===== OP-04 Cancel Reservation ====="
show "success: CONFIRMED cancelled 7 days ahead" post "$BASE/reservations/$R_CONFIRM/cancel" "$(actor $CUSTOMER)"
show "negative: CONFIRMED within the 24 h notice (starts in 12 h)" post "$BASE/reservations/$R_LATE/cancel" "$(actor $CUSTOMER)"

echo "===== OP-05 / OP-06 Approve and Reject (v0.2) ====="
show "success: confirmation of an approval-requiring companion -> PENDING_APPROVAL" post "$BASE/reservations/$R_APPROVE/confirm" "$(actor $CUSTOMER)"
show "negative: the customer cannot approve their own request" post "$BASE/reservations/$R_APPROVE/approve" "$(actor $CUSTOMER)"
show "success: the booked companion approves" post "$BASE/reservations/$R_APPROVE/approve" "$(actor $BEA_USER)"
show "negative: the customer cannot reject the request" post "$BASE/reservations/$R_REJECT/reject" "$(actor $CUSTOMER)"
show "success: the booked companion rejects another request" post "$BASE/reservations/$R_REJECT/reject" "$(actor $BEA_USER)"

echo "===== expiry of the approval window ====="
kill $SERVER 2>/dev/null || true
show "expire_pending_approvals (one request past its deadline)" "$PY" manage.py expire_pending_approvals
