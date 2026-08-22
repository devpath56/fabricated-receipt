"""
Run all three validation checks for a given invoice_id and return a
single combined result. This is what the Streamlit app and any CLI/API
layer should call.
"""
import sqlite3

from checks.job_status import check_job_status
from checks.vendor_resolution import check_vendor_resolution
from checks.duplicate_payment import check_duplicate_payment


def get_invoice(conn: sqlite3.Connection, invoice_id: str) -> sqlite3.Row:
    row = conn.execute(
        "SELECT * FROM invoices WHERE invoice_id = ?", (invoice_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"invoice_id '{invoice_id}' not found in Table 3.")
    return row


def run_all_checks(conn: sqlite3.Connection, invoice_id: str) -> dict:
    invoice = get_invoice(conn, invoice_id)

    results = [
        check_job_status(conn, invoice["fms_id"]),
        check_vendor_resolution(conn, invoice),
        check_duplicate_payment(conn, invoice),
    ]

    overall = "APPROVE" if all(r["passed"] for r in results) else "DENY"

    return {
        "invoice_id": invoice_id,
        "invoice": dict(invoice),
        "checks": results,
        "overall": overall,
    }


def run_all_invoices(conn: sqlite3.Connection) -> list[dict]:
    ids = [r["invoice_id"] for r in conn.execute("SELECT invoice_id FROM invoices")]
    return [run_all_checks(conn, i) for i in ids]
