"""
Check 2 -- vendor entity resolution.

Resolves a raw vendor string (e.g. invoices.vendor_name) to a canonical
vendor_id from vendors.csv, WITHOUT ever reading invoices.vendor_id --
that column is the answer key, not an input. Feeding it in would score
100% and prove nothing (see README).

Design:
  1. Normalize + block: build an index of every known (canonical name,
     alias) normalized string -> vendor_id.
  2. Score: exact match on the normalized string is the strong signal.
     If nothing matches exactly, fall back to fuzzy similarity against
     every known name and take the best candidate.
  3. Threshold decision:
       score == 1.0            -> auto-merge (exact-normalized)
       score >= FUZZY_THRESHOLD -> auto-merge (fuzzy), but flagged low-confidence
       otherwise                -> send to review queue, do not guess

Fail-closed: an uncertain match never gets a vendor_id assigned to it.
It goes to review with its best candidate attached (or none), and stays
there until a human confirms it.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import sys
from dataclasses import dataclass
from pathlib import Path

from checks.common import DATA_DIR, Vendor, load_vendors, normalize_name

FUZZY_THRESHOLD = 0.90     # auto-merge floor
REVIEW_THRESHOLD = 0.75    # below this, don't even suggest a candidate


@dataclass
class Resolution:
    input_name: str
    vendor_id: str | None
    canonical_name: str | None
    score: float
    method: str      # "exact" | "fuzzy" | "unresolved"
    status: str       # "merged" | "review"


class VendorResolver:
    def __init__(self, vendors: list[Vendor]):
        self.vendors = vendors
        # normalized name -> vendor_id, built from canonical name + every alias
        self.index: dict[str, str] = {}
        # normalized name -> vendor_id, kept as a flat list for fuzzy scoring
        self.norm_names: list[tuple[str, str]] = []
        collisions: dict[str, set[str]] = {}
        for v in vendors:
            names = [v.canonical_name] + v.aliases
            for n in names:
                key = normalize_name(n)
                if not key:
                    continue
                if key in self.index and self.index[key] != v.vendor_id:
                    collisions.setdefault(key, {self.index[key]}).add(v.vendor_id)
                self.index[key] = v.vendor_id
                self.norm_names.append((key, v.vendor_id))
        self.collisions = collisions   # two different vendor_ids normalize
                                         # to the same string -- a data guard,
                                         # not expected to fire on this dataset

    def resolve(self, raw_name: str) -> Resolution:
        key = normalize_name(raw_name)
        if not key:
            return Resolution(raw_name, None, None, 0.0, "unresolved", "review")

        if key in self.index:
            vid = self.index[key]
            canonical = next(v.canonical_name for v in self.vendors if v.vendor_id == vid)
            return Resolution(raw_name, vid, canonical, 1.0, "exact", "merged")

        best_score, best_vid = 0.0, None
        for cand_key, vid in self.norm_names:
            score = difflib.SequenceMatcher(None, key, cand_key).ratio()
            if score > best_score:
                best_score, best_vid = score, vid

        if best_vid and best_score >= FUZZY_THRESHOLD:
            canonical = next(v.canonical_name for v in self.vendors if v.vendor_id == best_vid)
            return Resolution(raw_name, best_vid, canonical, best_score, "fuzzy", "merged")

        if best_vid and best_score >= REVIEW_THRESHOLD:
            canonical = next(v.canonical_name for v in self.vendors if v.vendor_id == best_vid)
            return Resolution(raw_name, best_vid, canonical, best_score, "fuzzy", "review")

        return Resolution(raw_name, None, None, best_score, "unresolved", "review")


def run(data_dir: Path = None, invoices_path: Path = None) -> list[Resolution]:
    data_dir = data_dir or DATA_DIR
    vendors = load_vendors(data_dir / "vendors.csv")
    resolver = VendorResolver(vendors)

    invoices_path = invoices_path or data_dir / "invoices.csv"
    results = []
    with open(invoices_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            res = resolver.resolve(row["vendor_name"])
            results.append(res)

    if resolver.collisions:
        print(f"WARNING: {len(resolver.collisions)} normalized name(s) map to "
              f"more than one vendor_id -- vendor master has an unresolved "
              f"ambiguity:", file=sys.stderr)
        for key, vids in resolver.collisions.items():
            print(f"  {key!r} -> {sorted(vids)}", file=sys.stderr)

    return results


def _score_against_labels(results: list[Resolution], invoices_path: Path) -> None:
    """Optional: compare resolutions against invoices.vendor_id, for
    calibration only. This never feeds back into resolve() -- it's the
    ~20-hand-label-style sanity check the README asks for, run here
    against the full label set since it's cheap.
    """
    truth = {}
    with open(invoices_path, newline="", encoding="utf-8") as fh:
        for i, row in enumerate(csv.DictReader(fh)):
            truth[i] = row["vendor_id"]

    correct = sum(1 for i, r in enumerate(results) if r.vendor_id == truth[i])
    merged = sum(1 for r in results if r.status == "merged")
    review = sum(1 for r in results if r.status == "review")
    wrong_merges = sum(
        1 for i, r in enumerate(results)
        if r.status == "merged" and r.vendor_id != truth[i]
    )

    print(f"resolved: {len(results)}")
    print(f"  merged: {merged}  review: {review}")
    print(f"  accuracy vs label (calibration only): {correct}/{len(results)} "
          f"({correct/len(results):.1%})")
    print(f"  wrong auto-merges (should be 0, or investigate threshold): {wrong_merges}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=DATA_DIR)
    ap.add_argument("--score", action="store_true",
                     help="also report accuracy against invoices.vendor_id (calibration only)")
    args = ap.parse_args()

    results = run(args.data_dir)
    review_count = sum(1 for r in results if r.status == "review")
    print(f"vendor resolution: {len(results)} invoice rows, "
          f"{len(results) - review_count} auto-merged, {review_count} sent to review")

    if args.score:
        _score_against_labels(results, args.data_dir / "invoices.csv")
