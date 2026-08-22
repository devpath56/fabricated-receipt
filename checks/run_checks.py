"""
Runs check 2 (vendor entity resolution) then check 3 (duplicate payment
check), in that order, since check 3 depends on check 2's resolver.

    python3 checks/run_checks.py

Exits non-zero if either check fails closed -- mirrors the contract of
scripts/failures.mjs (baseline drift -> non-zero) so this can drop
straight into the same CI step.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duplicate_payment
import vendor_resolution
from common import DATA_DIR

if __name__ == "__main__":
    print("== check 2: vendor entity resolution ==")
    results = vendor_resolution.run(DATA_DIR)
    review = sum(1 for r in results if r.status == "review")
    print(f"{len(results)} rows, {len(results) - review} auto-merged, {review} sent to review\n")

    print("== check 3: duplicate payment check ==")
    findings, orphans = duplicate_payment.run(DATA_DIR)
    exact = [f for f in findings if f.kind == "exact"]
    blocked = [f for f in findings if f.action == "block"]
    print(f"orphan po_id: {len(orphans)}  exact duplicates: {len(exact)}  blocked: {len(blocked)}")

    exit_code = 0
    if len(exact) != duplicate_payment.EXPECTED_EXACT_DUPLICATES:
        print("FAIL: exact-duplicate baseline drifted", file=sys.stderr)
        exit_code = 1
    if blocked:
        print(f"FAIL (expected, fail-closed): {len(blocked)} pending payment(s) blocked", file=sys.stderr)
        exit_code = 1

    sys.exit(exit_code)
