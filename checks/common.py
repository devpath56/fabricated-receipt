"""
Shared loaders and normalization helpers for check 2 (vendor entity
resolution) and check 3 (duplicate payment check).

No third-party dependencies, matching the rest of this repo's scripts/
(stdlib only, deterministic, safe to run offline against the committed
CSVs in data/).
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

LEGAL_SUFFIXES = {
    "llc", "inc", "incorporated", "co", "corp", "corporation",
    "ltd", "limited", "lp", "llp", "pc", "pllc",
}


def normalize_name(name: str) -> str:
    """Collapse a vendor string down to a comparable key.

    Lowercases, strips punctuation, drops legal suffixes (LLC/Inc/Co/...),
    and collapses whitespace. This is check 2's normalization step --
    it is deliberately conservative (no phonetic matching, no address
    reasoning) so that every merge it makes is easy to audit by eye.
    """
    s = name.lower().strip()
    s = re.sub(r"[.,'\"]", "", s)          # drop light punctuation
    s = re.sub(r"[-/&]", " ", s)            # split on separators
    s = re.sub(r"\s+", " ", s).strip()
    tokens = [t for t in s.split(" ") if t not in LEGAL_SUFFIXES]
    return " ".join(tokens)


@dataclass
class Vendor:
    vendor_id: str
    canonical_name: str
    alias_count: int
    aliases: list[str] = field(default_factory=list)


@dataclass
class Invoice:
    invoice_id: str
    po_id: str
    vendor_id: str          # NB: the answer column. Never read this for
                             # resolution logic -- only for scoring/eval.
    vendor_name: str
    amount: float
    period: str
    status: str
    submitted_at: str
    doc_uri: str
    missing_field: str
    label_is_duplicate: bool
    label_dead_job: bool


@dataclass
class ErpRow:
    pid: str
    fms_id: str
    current_phase: str
    current_phase_norm: str
    agency_project_name: str
    forecast_completion: str
    job_open_for_charges: bool


def load_vendors(path: Path = None) -> list[Vendor]:
    path = path or DATA_DIR / "vendors.csv"
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            aliases = [a.strip() for a in row["aliases"].split("|") if a.strip()]
            out.append(Vendor(
                vendor_id=row["vendor_id"],
                canonical_name=row["canonical_name"],
                alias_count=int(row["alias_count"]),
                aliases=aliases,
            ))
    return out


def load_invoices(path: Path = None) -> list[Invoice]:
    path = path or DATA_DIR / "invoices.csv"
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(Invoice(
                invoice_id=row["invoice_id"],
                po_id=row["po_id"],
                vendor_id=row["vendor_id"],
                vendor_name=row["vendor_name"],
                amount=float(row["amount"]) if row["amount"] else 0.0,
                period=row["period"],
                status=row["status"],
                submitted_at=row["submitted_at"],
                doc_uri=row["doc_uri"],
                missing_field=row["missing_field"],
                label_is_duplicate=row["label_is_duplicate"] == "true",
                label_dead_job=row["label_dead_job"] == "true",
            ))
    return out


def load_erp(path: Path = None) -> list[ErpRow]:
    path = path or DATA_DIR / "erp.csv"
    out = []
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out.append(ErpRow(
                pid=row["pid"],
                fms_id=row["fms_id"],
                current_phase=row["current_phase"],
                current_phase_norm=row["current_phase_norm"],
                agency_project_name=row["agency_project_name"],
                forecast_completion=row["forecast_completion"],
                job_open_for_charges=row["job_open_for_charges"] == "true",
            ))
    return out
