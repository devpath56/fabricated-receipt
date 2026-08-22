"""
Check 3 -- duplicate payment check.

Runs AFTER check 2. Grouping by raw vendor_name would miss duplicates
that are the same vendor under two spellings, so this always resolves
through vendor_resolution.VendorResolver first.

Design:
  1. Join: invoices.po_id is, empirically, an fms_id (not a free PO
     number -- see README). Validate every po_id against erp.fms_id
     before doing anything else; an invoice whose po_id doesn't resolve
     is an orphan and gets flagged, not silently dropped.
  2. Resolve vendor_name -> vendor_id via check 2's resolver (never
     read invoices.vendor_id).
  3. Group invoices by (resolved_vendor_id, amount, period).
       exact duplicate:  same group AND same po_id           -> block
       near duplicate:   same group, different po_id,
                          submitted_at within NEAR_DUP_DAYS   -> review
  4. Fail-closed: any invoice still "pending" that lands in a flagged
     group is blocked before payment, not logged after the fact.
     Invoices already "paid" can't be blocked retroactively -- those are
     surfaced as a clawback list instead.
"""
from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from checks.common import DATA_DIR, load_erp, load_invoices
from checks.vendor_resolution import VendorResolver, load_vendors

NEAR_DUP_DAYS = 10

# Baseline from the committed, seeded invoices.csv -- mirrors the pattern
# in scripts/failures.mjs: assert a known figure, exit non-zero on drift,
# so this check and the fixture can't quietly disagree.
EXPECTED_EXACT_DUPLICATES = 41


@dataclass
class DuplicateFinding:
    invoice_id: str
    matched_invoice_id: str
    vendor_id: str
    amount: float
    period: str
    kind: str          # "exact" | "near"
    action: str         # "block" | "clawback" | "review"


def _parse_date(s: str) -> date | None:
    try:
        y, m, d = (int(p) for p in s.split("-"))
        return date(y, m, d)
    except (ValueError, AttributeError):
        return None


def find_orphan_pos(invoices, valid_fms_ids: set[str]) -> list[str]:
    """Invoices whose po_id does not resolve to any known fms_id."""
    return [inv.invoice_id for inv in invoices if inv.po_id and inv.po_id not in valid_fms_ids]


def find_duplicates(invoices, resolver: VendorResolver) -> list[DuplicateFinding]:
    groups: dict[tuple[str, float, str], list] = defaultdict(list)

    resolved = {}
    for inv in invoices:
        res = resolver.resolve(inv.vendor_name)
        resolved[inv.invoice_id] = res
        if res.vendor_id is None:
            continue  # can't group what didn't resolve -- surfaced separately
        groups[(res.vendor_id, inv.amount, inv.period)].append(inv)

    findings: list[DuplicateFinding] = []
    for (vendor_id, amount, period), members in groups.items():
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda i: i.submitted_at)
        first, rest = members[0], members[1:]
        for inv in rest:
            is_exact = inv.po_id == first.po_id
            if not is_exact:
                d1, d2 = _parse_date(first.submitted_at), _parse_date(inv.submitted_at)
                if not (d1 and d2 and abs((d2 - d1).days) <= NEAR_DUP_DAYS):
                    continue  # different PO, too far apart in time -- not a match
            kind = "exact" if is_exact else "near"
            if inv.status == "pending":
                action = "block"
            elif inv.status == "paid":
                action = "clawback"
            else:
                action = "review"  # e.g. already denied -- nothing to do, but logged
            findings.append(DuplicateFinding(
                invoice_id=inv.invoice_id,
                matched_invoice_id=first.invoice_id,
                vendor_id=vendor_id,
                amount=amount,
                period=period,
                kind=kind,
                action=action,
            ))
    return findings


def run(data_dir: Path = None) -> tuple[list[DuplicateFinding], list[str]]:
    data_dir = data_dir or DATA_DIR
    erp = load_erp(data_dir / "erp.csv")
    invoices = load_invoices(data_dir / "invoices.csv")
    vendors = load_vendors(data_dir / "vendors.csv")
    resolver = VendorResolver(vendors)

    valid_fms_ids = {row.fms_id for row in erp}
    orphans = find_orphan_pos(invoices, valid_fms_ids)
    findings = find_duplicates(invoices, resolver)
    return findings, orphans


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    ap.add_argument("--no-assert", action="store_true",
                     help="skip the baseline assertion (for exploring new data)")
    args = ap.parse_args()

    findings, orphans = run(args.data_dir)

    exact = [f for f in findings if f.kind == "exact"]
    near = [f for f in findings if f.kind == "near"]
    blocked = [f for f in findings if f.action == "block"]
    clawback = [f for f in findings if f.action == "clawback"]

    print(f"duplicate payment check:")
    print(f"  orphan po_id (no matching fms_id): {len(orphans)}")
    print(f"  exact duplicates: {len(exact)}  near duplicates: {len(near)}")
    print(f"  blocked before payment: {len(blocked)}  flagged for clawback: {len(clawback)}")

    if not args.no_assert:
        if len(exact) != EXPECTED_EXACT_DUPLICATES:
            print(
                f"FAIL: expected {EXPECTED_EXACT_DUPLICATES} exact duplicates "
                f"in the seeded fixture, found {len(exact)}. Either the "
                f"generator drifted or the guard regressed -- investigate "
                f"before trusting this check.",
                file=sys.stderr,
            )
            sys.exit(1)

    if blocked:
        sys.exit(1)  # fail closed: at least one pending payment must not go out
