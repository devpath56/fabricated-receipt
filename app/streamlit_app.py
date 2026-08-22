"""
Streamlit frontend for the invoice validation module.

Run from the repo root:
    streamlit run app/streamlit_app.py

Requires data/capital_projects.db to already exist (run etl/upsert.py and
etl/seed_table3.py first) -- see the sidebar for a one-click loader if it's
missing.
"""
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

# Make the sibling `checks/` and `etl/` packages importable when Streamlit
# is launched from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from checks.db import get_conn
from checks.run_checks import run_all_checks, run_all_invoices

DB_PATH_DEFAULT = "data/capital_projects.db"

st.set_page_config(page_title="Invoice Validation", layout="wide")
st.title("Capital Projects — Invoice Validation")
st.caption(
    "Three checks per invoice: Job Status (Table 1) · Vendor Resolution "
    "(vendor_master + fms_vendor) · Duplicate Payment (Table 3 self-check)."
)

# ── sidebar: db path + status ───────────────────────────────────────────
st.sidebar.header("Database")
db_path = st.sidebar.text_input("SQLite path", value=DB_PATH_DEFAULT)

if not Path(db_path).exists():
    st.sidebar.error("Database not found.")
    st.sidebar.code(
        f"python etl/upsert.py --db {db_path} \\\n"
        f"  --table1 data/raw/table1.csv --table2 data/raw/table2.csv\n"
        f"python etl/seed_table3.py --db {db_path}",
        language="bash",
    )
    st.stop()

conn = get_conn(db_path)


def status_badge(passed: bool) -> str:
    return "✅ PASS" if passed else "❌ FAIL"


# ── tabs ─────────────────────────────────────────────────────────────────
tab_single, tab_bulk = st.tabs(["Check one invoice", "Run all invoices"])

with tab_single:
    invoice_ids = [
        r["invoice_id"] for r in conn.execute("SELECT invoice_id FROM invoices ORDER BY invoice_id")
    ]
    selected = st.selectbox("Invoice", invoice_ids)

    if selected:
        result = run_all_checks(conn, selected)
        inv = result["invoice"]

        col1, col2 = st.columns([1, 2])
        with col1:
            st.subheader("Invoice")
            st.write(
                {
                    "fms_id": inv["fms_id"],
                    "vendor_id": inv["vendor_id"],
                    "vendor_name": inv["vendor_name"],
                    "invoice_number": inv["invoice_number"],
                    "billing_period": inv["billing_period"],
                    "amount": f"${inv['amount']:,.2f}",
                    "payment_status": inv["payment_status"],
                }
            )
            overall_color = "green" if result["overall"] == "APPROVE" else "red"
            st.markdown(f"### Overall: :{overall_color}[{result['overall']}]")

        with col2:
            st.subheader("Checks")
            for check in result["checks"]:
                with st.expander(f"{status_badge(check['passed'])}  —  {check['check']}", expanded=not check["passed"]):
                    st.write(check["reason"])
                    extra = {k: v for k, v in check.items() if k not in ("check", "passed", "reason")}
                    if extra:
                        st.json(extra)

with tab_bulk:
    st.subheader("All invoices")
    if st.button("Run checks on every invoice"):
        with st.spinner("Running checks..."):
            all_results = run_all_invoices(conn)

        rows = []
        for r in all_results:
            checks_by_name = {c["check"]: c["passed"] for c in r["checks"]}
            rows.append(
                {
                    "invoice_id": r["invoice_id"],
                    "fms_id": r["invoice"]["fms_id"],
                    "vendor_name": r["invoice"]["vendor_name"],
                    "amount": r["invoice"]["amount"],
                    "payment_status": r["invoice"]["payment_status"],
                    "job_status": status_badge(checks_by_name["job_status"]),
                    "vendor_resolution": status_badge(checks_by_name["vendor_resolution"]),
                    "duplicate_payment": status_badge(checks_by_name["duplicate_payment"]),
                    "overall": r["overall"],
                }
            )
        df = pd.DataFrame(rows)

        def highlight_overall(row):
            color = "background-color: #d4f4dd" if row["overall"] == "APPROVE" else "background-color: #fbdada"
            return [color] * len(row)

        st.dataframe(df.style.apply(highlight_overall, axis=1), use_container_width=True)

        st.download_button(
            "Download results as CSV",
            df.to_csv(index=False).encode("utf-8"),
            file_name="invoice_check_results.csv",
            mime="text/csv",
        )
