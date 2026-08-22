"""
Check 2 — Vendor Resolution
Does the vendor named on the invoice actually belong to this fms_id?

Two things have to be true:
1. The invoice's vendor_id must match the vendor_id on file in fms_vendor
   for this fms_id (the contract-of-record check).
2. The invoice's raw vendor_name must resolve, via fuzzy match, to the
   canonical name for that vendor_id in vendor_master (the entity-
   resolution / data-quality check).

Uses difflib (stdlib) by default; swaps in rapidfuzz automatically if it's
installed, since rapidfuzz gives much better results on real-world messy
vendor names.
"""
import sqlite3
from difflib import SequenceMatcher

try:
    from rapidfuzz import fuzz as _rapidfuzz_fuzz
    _HAVE_RAPIDFUZZ = True
except ImportError:
    _HAVE_RAPIDFUZZ = False

SIMILARITY_THRESHOLD = 0.75  # 0-1 scale


def _similarity(a: str, b: str) -> float:
    a_norm, b_norm = a.strip().lower(), b.strip().lower()
    if _HAVE_RAPIDFUZZ:
        return _rapidfuzz_fuzz.ratio(a_norm, b_norm) / 100.0
    return SequenceMatcher(None, a_norm, b_norm).ratio()


def check_vendor_resolution(conn: sqlite3.Connection, invoice: sqlite3.Row) -> dict:
    fms_id = invoice["fms_id"]
    claimed_vendor_id = invoice["vendor_id"]
    raw_vendor_name = invoice["vendor_name"]

    contract = conn.execute(
        "SELECT vendor_id FROM fms_vendor WHERE fms_id = ?", (fms_id,)
    ).fetchone()

    if contract is None:
        return {
            "check": "vendor_resolution",
            "passed": False,
            "reason": f"No vendor is on file for fms_id '{fms_id}' at all — cannot validate.",
        }

    expected_vendor_id = contract["vendor_id"]

    if claimed_vendor_id != expected_vendor_id:
        return {
            "check": "vendor_resolution",
            "passed": False,
            "reason": (
                f"Invoice claims vendor_id {claimed_vendor_id}, but the contract "
                f"of record for fms_id {fms_id} is vendor_id {expected_vendor_id}."
            ),
            "expected_vendor_id": expected_vendor_id,
            "claimed_vendor_id": claimed_vendor_id,
        }

    canonical = conn.execute(
        "SELECT vendor_name FROM vendor_master WHERE vendor_id = ?",
        (expected_vendor_id,),
    ).fetchone()

    if canonical is None:
        return {
            "check": "vendor_resolution",
            "passed": False,
            "reason": f"vendor_id {expected_vendor_id} has no entry in vendor_master.",
        }

    canonical_name = canonical["vendor_name"]
    score = _similarity(raw_vendor_name, canonical_name)

    if score < SIMILARITY_THRESHOLD:
        return {
            "check": "vendor_resolution",
            "passed": False,
            "reason": (
                f"vendor_id matches ({expected_vendor_id}), but the submitted name "
                f"'{raw_vendor_name}' only scores {score:.2f} similarity against the "
                f"canonical name '{canonical_name}' (threshold {SIMILARITY_THRESHOLD}). "
                "Flag for manual review — possible data entry error or identity mismatch."
            ),
            "similarity": round(score, 3),
            "canonical_name": canonical_name,
        }

    return {
        "check": "vendor_resolution",
        "passed": True,
        "reason": (
            f"vendor_id {expected_vendor_id} matches the contract of record for "
            f"fms_id {fms_id}, and '{raw_vendor_name}' resolves to '{canonical_name}' "
            f"at {score:.2f} similarity."
        ),
        "similarity": round(score, 3),
        "canonical_name": canonical_name,
    }
