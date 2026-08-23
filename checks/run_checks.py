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

# PACKAGE IMPORTS, matching every sibling in this directory. These three lines were flat
# (`import duplicate_payment`, `from common import ...`) while duplicate_payment.py and
# vendor_resolution.py both do `from checks.common import ...`. The two styles cannot both work:
# run from the repo root, the flat imports fail; run from inside checks/, the siblings' package
# imports fail. So this entry point was unrunnable from ANY directory, and nothing noticed because
# the Streamlit app imports the check modules directly and never goes through here.
from checks import duplicate_payment
from checks import vendor_resolution
from checks.common import DATA_DIR

if __name__ == "__main__":
    # SAY WHAT THIS COVERS. This runner executes checks 2 and 3 only. Checks 1 (intake) and 4
    # (job status) are PER-INVOICE and run in the app; 2 and 3 are corpus-wide and run here. That
    # split is deliberate, but a runner that reports a clean result over half the checks without
    # naming which half is the exact failure this product exists to catch -- a confident number
    # whose population was never stated.
    print("SCOPE: checks 2 and 3 only (corpus-wide). Checks 1 and 4 are per-invoice and run in")
    print("       the app -- they are NOT executed here and this output says nothing about them.")
    print()
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
