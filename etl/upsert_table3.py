"""
Upsert REAL Table 3 (invoice) data into SQLite -- replaces etl/seed_table3.py
once you have actual invoice records instead of synthetic demo ones.

Expected table3.csv columns (case-insensitive, flexible on separators --
see COLUMN_ALIASES below if your export uses different header names):
    invoice_id, fms_id, vendor_id, vendor_name, invoice_number,
    billing_period, amount, payment_status

Optionally also loads real vendor tables if you have them:
    --vendors   CSV with vendor_id, vendor_name        -> vendor_master
    --fms-vendor CSV with fms_id, vendor_id             -> fms_vendor
(Skip these flags and the existing vendor_master / fms_vendor rows --
e.g. from etl/seed_table3.py -- are left as-is.)

Usage:
    python etl/upsert_table3.py \
        --db data/capital_projects.db \
        --table3 data/raw/table3.csv \
        [--vendors data/raw/vendors.csv] \
        [--fms-vendor data/raw/fms_vendor.csv]

Safe to re-run: INSERT OR REPLACE keyed on invoice_id (and on vendor_id /
fms_id for the optional tables) -- re-running with a fresher export
refreshes existing rows and adds new ones, never duplicates.
"""
import argparse
import re
import sqlite3
from pathlib import Path

import pandas as pd

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"

VALID_STATUSES = {"SUBMITTED", "APPROVED", "PAID", "DENIED"}

# Maps expected internal field -> list of header spellings we'll accept.
# Add more variants here if your export uses different names.
COLUMN_ALIASES = {
    "invoice_id":      ["invoice_id", "invoice id", "id"],
    "fms_id":          ["fms_id", "fms id"],
    "vendor_id":       ["vendor_id", "vendor id"],
    "vendor_name":     ["vendor_name", "vendor", "vendor name", "contractor_name"],
    "invoice_number":  ["invoice_number", "invoice number", "invoice_no", "invoice #"],
    "billing_period":  ["billing_period", "billing period", "period"],
    "amount":          ["amount", "invoice_amount", "amount billed"],
    "payment_status":  ["payment_status", "status", "payment status"],
}


def resolve_columns(df: pd.DataFrame) -> dict:
    """Map internal field names -> actual column name found in the CSV."""
    lower_cols = {c.lower().strip(): c for c in df.columns}
    resolved = {}
    missing = []
    for field, aliases in COLUMN_ALIASES.items():
        found = next((lower_cols[a] for a in aliases if a in lower_cols), None)
        if found is None:
            missing.append(field)
        else:
            resolved[field] = found
    if missing:
        raise SystemExit(
            f"table3.csv is missing required column(s): {missing}\n"
            f"Found columns: {list(df.columns)}\n"
            f"Add the real header name to COLUMN_ALIASES in this script if it's just a naming mismatch."
        )
    return resolved


def clean_currency(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip().replace("$", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def clean_text(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    return s if s else None


def normalize_billing_period(val):
    """Accepts 'May 2026', '2026-05', '05/2026', etc. -> 'YYYY-MM' where possible."""
    s = clean_text(val)
    if s is None:
        return None
    m = re.match(r"^(\d{4})-(\d{2})$", s)
    if m:
        return s
    m = re.match(r"^(\d{2})/(\d{4})$", s)
    if m:
        return f"{m.group(2)}-{m.group(1)}"
    return s  # leave as-is if it doesn't match a known pattern; don't silently guess


def normalize_status(val):
    s = clean_text(val)
    if s is None:
        return None
    s_up = s.upper()
    return s_up if s_up in VALID_STATUSES else s_up  # let the CHECK constraint catch anything bad


def ensure_schema(conn: sqlite3.Connection):
    conn.executescript(SCHEMA_PATH.read_text())


def upsert_table3(conn: sqlite3.Connection, csv_path: str) -> int:
    df = pd.read_csv(csv_path, dtype=str)
    cols = resolve_columns(df)

    rows = []
    rejected = []
    for i, r in df.iterrows():
        invoice_id = clean_text(r.get(cols["invoice_id"]))
        fms_id = clean_text(r.get(cols["fms_id"]))
        vendor_id = clean_text(r.get(cols["vendor_id"]))
        invoice_number = clean_text(r.get(cols["invoice_number"]))
        billing_period = normalize_billing_period(r.get(cols["billing_period"]))
        amount = clean_currency(r.get(cols["amount"]))
        status = normalize_status(r.get(cols["payment_status"]))

        if not all([invoice_id, fms_id, vendor_id, invoice_number, billing_period]) or amount is None:
            rejected.append((i, dict(r)))
            continue
        if status not in VALID_STATUSES:
            rejected.append((i, dict(r)))
            continue

        rows.append((
            invoice_id, fms_id, vendor_id,
            clean_text(r.get(cols["vendor_name"])) or "UNKNOWN",
            invoice_number, billing_period, amount, status,
        ))

    conn.executemany(
        """
        INSERT INTO invoices (
            invoice_id, fms_id, vendor_id, vendor_name,
            invoice_number, billing_period, amount, payment_status
        ) VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(invoice_id) DO UPDATE SET
            fms_id=excluded.fms_id,
            vendor_id=excluded.vendor_id,
            vendor_name=excluded.vendor_name,
            invoice_number=excluded.invoice_number,
            billing_period=excluded.billing_period,
            amount=excluded.amount,
            payment_status=excluded.payment_status
        """,
        rows,
    )
    conn.commit()

    if rejected:
        print(f"  WARNING: {len(rejected)} row(s) skipped (missing required field or bad payment_status).")
        for i, r in rejected[:5]:
            print(f"    row {i}: {r}")
        if len(rejected) > 5:
            print(f"    ... and {len(rejected) - 5} more")

    return len(rows)


def upsert_vendors(conn: sqlite3.Connection, csv_path: str) -> int:
    df = pd.read_csv(csv_path, dtype=str)
    rows = [
        (clean_text(r.get("vendor_id")), clean_text(r.get("vendor_name")))
        for _, r in df.iterrows()
        if clean_text(r.get("vendor_id")) and clean_text(r.get("vendor_name"))
    ]
    conn.executemany(
        "INSERT INTO vendor_master (vendor_id, vendor_name) VALUES (?, ?) "
        "ON CONFLICT(vendor_id) DO UPDATE SET vendor_name=excluded.vendor_name",
        rows,
    )
    conn.commit()
    return len(rows)


def upsert_fms_vendor(conn: sqlite3.Connection, csv_path: str) -> int:
    df = pd.read_csv(csv_path, dtype=str)
    rows = [
        (clean_text(r.get("fms_id")), clean_text(r.get("vendor_id")))
        for _, r in df.iterrows()
        if clean_text(r.get("fms_id")) and clean_text(r.get("vendor_id"))
    ]
    conn.executemany(
        "INSERT INTO fms_vendor (fms_id, vendor_id) VALUES (?, ?) "
        "ON CONFLICT(fms_id) DO UPDATE SET vendor_id=excluded.vendor_id",
        rows,
    )
    conn.commit()
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--table3", required=True, help="Real invoice CSV")
    ap.add_argument("--vendors", help="Optional: real vendor_id -> vendor_name CSV")
    ap.add_argument("--fms-vendor", help="Optional: real fms_id -> vendor_id CSV")
    args = ap.parse_args()

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    ensure_schema(conn)

    if args.vendors:
        n = upsert_vendors(conn, args.vendors)
        print(f"vendor_master: upserted {n} rows")

    if args.fms_vendor:
        n = upsert_fms_vendor(conn, args.fms_vendor)
        print(f"fms_vendor: upserted {n} rows")

    n = upsert_table3(conn, args.table3)
    print(f"invoices: upserted {n} rows")

    conn.close()


if __name__ == "__main__":
    main()
