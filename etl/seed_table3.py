"""
Seed vendor_master, fms_vendor, and 15 synthetic invoices into Table 3.

Grounded in real data: every fms_id used is pulled live from
budget_and_schedule (Table 1) at the latest reporting_period on file, and
every invoice amount is sized as a fraction of that fms_id's real
total_budget. Nothing here invents an fms_id.

Usage:
    python etl/seed_table3.py --db data/capital_projects.db
"""
import argparse
import random
import sqlite3

random.seed(7)  # reproducible demo data

VENDORS = [
    ("V001", "ABC Construction Inc."),
    ("V002", "Metro Fire & Safety LLC"),
    ("V003", "Empire Roofing Corp."),
    ("V004", "Five Boro Electrical"),
    ("V005", "Hudson Valley HVAC Group"),
    ("V006", "Bedrock Concrete & Masonry"),
]

# vendor_name variants used on invoices -- some are the canonical spelling,
# some are deliberately messy, to give vendor resolution real work to do.
VENDOR_NAME_VARIANTS = {
    "V001": ["ABC Construction Inc.", "ABC Const.", "ABC Construction, Inc."],
    "V002": ["Metro Fire & Safety LLC", "Metro Fire and Safety"],
    "V003": ["Empire Roofing Corp.", "Empire Roofing"],
    "V004": ["Five Boro Electrical", "5 Boro Electrical LLC"],
    "V005": ["Hudson Valley HVAC Group", "Hudson Valley HVAC"],
    "V006": ["Bedrock Concrete & Masonry", "Bedrock Concrete"],
}

TERMINAL_PHASES = {"Completed", "Rescinded", "Cancelled"}


def latest_snapshot_rows(conn):
    """One row per fms_id: the row at its own latest reporting_period."""
    cur = conn.execute("""
        SELECT b.fms_id, b.current_phase, b.total_budget, b.fms_project_name
        FROM budget_and_schedule b
        JOIN (
            SELECT fms_id, MAX(reporting_period) AS maxp
            FROM budget_and_schedule
            GROUP BY fms_id
        ) latest ON latest.fms_id = b.fms_id AND latest.maxp = b.reporting_period
        WHERE b.total_budget IS NOT NULL AND b.total_budget > 0
    """)
    return cur.fetchall()


def pick_fms_ids(conn, n_active=7, n_terminal=3):
    rows = latest_snapshot_rows(conn)
    active = [r for r in rows if r[1] not in TERMINAL_PHASES]
    terminal = [r for r in rows if r[1] in TERMINAL_PHASES]
    if len(active) < n_active or len(terminal) < n_terminal:
        raise SystemExit(
            f"Not enough rows to seed from (active={len(active)}, terminal={len(terminal)}). "
            "Run etl/upsert.py first."
        )
    return random.sample(active, n_active) + random.sample(terminal, n_terminal)


def seed_vendors(conn):
    conn.executemany(
        "INSERT OR REPLACE INTO vendor_master (vendor_id, vendor_name) VALUES (?, ?)",
        VENDORS,
    )


def seed_fms_vendor(conn, chosen_projects):
    vendor_ids = [v[0] for v in VENDORS]
    rows = []
    for fms_id, *_ in chosen_projects:
        rows.append((fms_id, random.choice(vendor_ids)))
    conn.executemany(
        "INSERT OR REPLACE INTO fms_vendor (fms_id, vendor_id) VALUES (?, ?)",
        rows,
    )
    return dict(rows)


def seed_invoices(conn, chosen_projects, fms_to_vendor):
    periods = ["2026-04", "2026-05", "2026-06"]
    invoices = []
    inv_n = 1000

    def next_invoice_id():
        nonlocal inv_n
        inv_n += 1
        return f"INV-{inv_n}"

    # Regular invoices, one or two per project
    for fms_id, phase, total_budget, _name in chosen_projects:
        vendor_id = fms_to_vendor[fms_id]
        n_invoices = random.choice([1, 2])
        for _ in range(n_invoices):
            amount = round(total_budget * random.uniform(0.05, 0.35), 2)
            vendor_name = random.choice(VENDOR_NAME_VARIANTS[vendor_id])
            invoices.append({
                "invoice_id": next_invoice_id(),
                "fms_id": fms_id,
                "vendor_id": vendor_id,
                "vendor_name": vendor_name,
                "invoice_number": f"{vendor_id}-{random.randint(1000, 9999)}",
                "billing_period": random.choice(periods),
                "amount": amount,
                "payment_status": random.choice(["SUBMITTED", "APPROVED", "PAID"]),
            })

    # Trim/extend to exactly 13 organic invoices, then add 2 deliberate
    # duplicate-payment cases (13 + 2 = 15).
    invoices = invoices[:13]
    while len(invoices) < 13:
        fms_id, phase, total_budget, _name = random.choice(chosen_projects)
        vendor_id = fms_to_vendor[fms_id]
        amount = round(total_budget * random.uniform(0.05, 0.35), 2)
        invoices.append({
            "invoice_id": next_invoice_id(),
            "fms_id": fms_id,
            "vendor_id": vendor_id,
            "vendor_name": random.choice(VENDOR_NAME_VARIANTS[vendor_id]),
            "invoice_number": f"{vendor_id}-{random.randint(1000, 9999)}",
            "billing_period": random.choice(periods),
            "amount": amount,
            "payment_status": random.choice(["SUBMITTED", "APPROVED", "PAID", "DENIED"]),
        })

    # Case A: exact duplicate -- same invoice_number, fms_id, period, amount.
    base = dict(invoices[0])
    base["invoice_id"] = next_invoice_id()
    base["payment_status"] = "PAID"
    invoices.append(base)

    # Case B: fuzzy duplicate -- same fms_id/period/amount/vendor_id, new
    # invoice_number, a vendor_name variant.
    src = invoices[1]
    fuzzy = dict(src)
    fuzzy["invoice_id"] = next_invoice_id()
    fuzzy["invoice_number"] = f"{src['vendor_id']}-{random.randint(1000, 9999)}"
    fuzzy["vendor_name"] = random.choice(VENDOR_NAME_VARIANTS[src["vendor_id"]])
    fuzzy["payment_status"] = "APPROVED"
    invoices.append(fuzzy)

    conn.executemany(
        """
        INSERT OR REPLACE INTO invoices (
            invoice_id, fms_id, vendor_id, vendor_name, invoice_number,
            billing_period, amount, payment_status
        ) VALUES (:invoice_id, :fms_id, :vendor_id, :vendor_name,
                   :invoice_number, :billing_period, :amount, :payment_status)
        """,
        invoices,
    )
    return invoices


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    chosen = pick_fms_ids(conn)

    seed_vendors(conn)
    fms_to_vendor = seed_fms_vendor(conn, chosen)
    invoices = seed_invoices(conn, chosen, fms_to_vendor)
    conn.commit()

    print(f"Seeded {len(VENDORS)} vendors, {len(chosen)} fms_vendor links, {len(invoices)} invoices.")
    print("\nProjects used (grounded in Table 1):")
    for fms_id, phase, total_budget, name in chosen:
        print(f"  {fms_id:12s} phase={phase:12s} budget=${total_budget:,.0f}  {name}")

    conn.close()


if __name__ == "__main__":
    main()
