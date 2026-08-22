"""
Check 3 — Duplicate Payment
Has this invoice (or an equivalent one) already been submitted or paid?

Two passes, cheapest/most-certain first:
1. Exact invoice_number reuse against a PAID/APPROVED invoice.
2. Fingerprint match: same fms_id + billing_period + amount + vendor_id,
   a DIFFERENT invoice_number, already PAID/APPROVED — catches the same
   payment resubmitted under a new invoice number (often paired with a
   vendor_name spelling variant, which is why Check 2 runs first).
"""
import sqlite3

LOCKED_STATUSES = ("PAID", "APPROVED")


def check_duplicate_payment(conn: sqlite3.Connection, invoice: sqlite3.Row) -> dict:
    invoice_id = invoice["invoice_id"]

    exact = conn.execute(
        f"""
        SELECT invoice_id, payment_status FROM invoices
        WHERE invoice_number = ?
          AND invoice_id != ?
          AND payment_status IN ({",".join("?" * len(LOCKED_STATUSES))})
        """,
        (invoice["invoice_number"], invoice_id, *LOCKED_STATUSES),
    ).fetchone()

    if exact is not None:
        return {
            "check": "duplicate_payment",
            "passed": False,
            "reason": (
                f"invoice_number '{invoice['invoice_number']}' was already submitted "
                f"as {exact['invoice_id']}, currently {exact['payment_status']}."
            ),
            "duplicate_of": exact["invoice_id"],
            "match_type": "exact_invoice_number",
        }

    fingerprint = conn.execute(
        f"""
        SELECT invoice_id, invoice_number, payment_status FROM invoices
        WHERE fms_id = ? AND billing_period = ? AND amount = ? AND vendor_id = ?
          AND invoice_id != ?
          AND payment_status IN ({",".join("?" * len(LOCKED_STATUSES))})
        """,
        (
            invoice["fms_id"], invoice["billing_period"], invoice["amount"],
            invoice["vendor_id"], invoice_id, *LOCKED_STATUSES,
        ),
    ).fetchone()

    if fingerprint is not None:
        return {
            "check": "duplicate_payment",
            "passed": False,
            "reason": (
                f"Same fms_id / billing_period / amount / vendor_id already exists "
                f"under invoice {fingerprint['invoice_id']} "
                f"(invoice_number '{fingerprint['invoice_number']}'), currently "
                f"{fingerprint['payment_status']} — likely a duplicate resubmission."
            ),
            "duplicate_of": fingerprint["invoice_id"],
            "match_type": "fingerprint",
        }

    return {
        "check": "duplicate_payment",
        "passed": True,
        "reason": "No matching invoice_number or fingerprint found among PAID/APPROVED invoices.",
    }
