#!/usr/bin/env bash
# C08 demo: evidence for REQ-04 + BR-02 (Confirm) -> ADR-01 -> DD C05 (Approval Policy), as tests.
# Usage: scripts/demo_c08.sh   (from the repository root)
set -euo pipefail

PY="$PWD/.venv/bin/python"
T=src/reservations/tests

echo "== (a) positive: touching intervals and a plain confirm succeed =="
"$PY" -m pytest -v \
  "$T/test_confirm.py::test_touching_intervals_can_both_be_confirmed" \
  "$T/test_availability.py::test_touching_intervals_do_not_overlap" \
  "$T/test_confirm.py::test_customer_confirms_draft"

echo "== (b) negative: overlap on Confirm -> 409 OVERLAP =="
"$PY" -m pytest -v \
  "$T/test_confirm.py::test_rejects_overlap_with_confirmed" \
  "$T/test_confirm.py::test_only_one_of_two_conflicting_confirmations_wins"

echo "== (c) concurrency: two parallel confirms, exactly one wins =="
"$PY" -m pytest -v "$T/test_concurrency.py"

echo "== (d) approval: BR-02 re-check on Approve + Approval Policy (C05) =="
"$PY" -m pytest -v \
  "$T/test_approve.py::test_approval_is_refused_when_the_slot_got_taken" \
  "$T/test_approve.py::test_approval_after_the_deadline_expires_the_request" \
  "$T/test_approval_policy.py"

echo "== (e) architecture (ADR-01 rules) =="
"$PY" -m pytest -v "$T/test_architecture.py"
"$PY" scripts/check_architecture.py
