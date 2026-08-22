"""
Upsert the two NYC Capital Projects Dashboard CSVs into SQLite.

Table 1 -> budget_and_schedule   ("Citywide Budget and Schedule" export)
Table 2 -> spend_history         ("Budget Spend History and Variance" export)

Usage:
    python etl/upsert.py \
        --db data/capital_projects.db \
        --table1 data/raw/Capital_Projects_Dashboard_-_Citywide_Budget_and_Schedule.csv \
        --table2 data/raw/Capital_Projects_Dashboard_-_Citywide_Budget_Spend_History_and_Variance.csv

Safe to re-run: uses INSERT OR REPLACE keyed on the same primary key as
schema.sql, so re-running with a newer export just refreshes existing rows
and adds new ones -- it never duplicates.
"""
import argparse
import re
import sqlite3
from pathlib import Path

import pandas as pd

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"


def clean_currency(val):
    """'$1,284,000' -> 1284000.0 ; '' / NaN -> None"""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    if s == "" or s.lower() == "nan":
        return None
    s = s.replace("$", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def clean_pct(val):
    """'12.5%' -> 0.125 ; '' / NaN -> None"""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    if s == "" or s.lower() == "nan":
        return None
    s = s.replace("%", "")
    try:
        return float(s) / 100.0
    except ValueError:
        return None


def clean_text(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    s = str(val).strip()
    return s if s else None


def clean_phase(val):
    """'(Pre-Design)' -> 'Pre-Design'"""
    s = clean_text(val)
    if s is None:
        return None
    return re.sub(r"^\((.*)\)$", r"\1", s)


def ensure_schema(conn: sqlite3.Connection):
    conn.executescript(SCHEMA_PATH.read_text())


def upsert_table1(conn: sqlite3.Connection, csv_path: str) -> int:
    df = pd.read_csv(csv_path, dtype=str)
    rows = []
    for _, r in df.iterrows():
        fms_id = clean_text(r.get("FMS ID"))
        period = clean_text(r.get("Reporting Period"))
        if not fms_id or not period:
            continue  # both are required by the primary key
        rows.append((
            period,
            clean_text(r.get("Managing Agency")),
            clean_text(r.get("Sponsor Agency")),
            clean_text(r.get("PID")),
            fms_id,
            clean_currency(r.get("Total Budget")),
            clean_currency(r.get("Spend to Date")),
            clean_pct(r.get("Spend to Date (%)")),
            clean_text(r.get("FMS Project Name")),
            clean_text(r.get("Agency Project Name")),
            clean_text(r.get("Agency Project Description")),
            clean_phase(r.get("Current Phase")),
            clean_text(r.get("Borough")),
            clean_text(r.get("Community Board")),
            clean_text(r.get("Budget Line")),
            clean_text(r.get("Ten Year Plan Category")),
            clean_text(r.get("FMS Data Date")),
        ))

    conn.executemany(
        """
        INSERT INTO budget_and_schedule (
            reporting_period, managing_agency, sponsor_agency, pid, fms_id,
            total_budget, spend_to_date, spend_to_date_pct,
            fms_project_name, agency_project_name, agency_project_description,
            current_phase, borough, community_board, budget_line,
            ten_year_plan_category, fms_data_date
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(fms_id, reporting_period) DO UPDATE SET
            managing_agency=excluded.managing_agency,
            sponsor_agency=excluded.sponsor_agency,
            pid=excluded.pid,
            total_budget=excluded.total_budget,
            spend_to_date=excluded.spend_to_date,
            spend_to_date_pct=excluded.spend_to_date_pct,
            fms_project_name=excluded.fms_project_name,
            agency_project_name=excluded.agency_project_name,
            agency_project_description=excluded.agency_project_description,
            current_phase=excluded.current_phase,
            borough=excluded.borough,
            community_board=excluded.community_board,
            budget_line=excluded.budget_line,
            ten_year_plan_category=excluded.ten_year_plan_category,
            fms_data_date=excluded.fms_data_date
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def upsert_table2(conn: sqlite3.Connection, csv_path: str) -> int:
    df = pd.read_csv(csv_path, dtype=str)
    rows = []
    for _, r in df.iterrows():
        fms_id = clean_text(r.get("FMS ID"))
        ym = clean_text(r.get("Year-Month Reported"))
        if not fms_id or not ym:
            continue
        rows.append((
            clean_text(r.get("Managing Agency")),
            fms_id,
            ym,
            clean_currency(r.get("Total Budget")),
            clean_currency(r.get("Spend to Date")),
            clean_pct(r.get("Spend to Date %")),
            clean_currency(r.get("Budget Variance")),
            clean_pct(r.get("Budget Variance %")),
        ))

    conn.executemany(
        """
        INSERT INTO spend_history (
            managing_agency, fms_id, year_month_reported,
            total_budget, spend_to_date, spend_to_date_pct,
            budget_variance, budget_variance_pct
        ) VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT(fms_id, year_month_reported) DO UPDATE SET
            managing_agency=excluded.managing_agency,
            total_budget=excluded.total_budget,
            spend_to_date=excluded.spend_to_date,
            spend_to_date_pct=excluded.spend_to_date_pct,
            budget_variance=excluded.budget_variance,
            budget_variance_pct=excluded.budget_variance_pct
        """,
        rows,
    )
    conn.commit()
    return len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--table1", required=True, help="Citywide Budget and Schedule CSV")
    ap.add_argument("--table2", required=True, help="Budget Spend History and Variance CSV")
    args = ap.parse_args()

    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(args.db)
    ensure_schema(conn)

    n1 = upsert_table1(conn, args.table1)
    print(f"budget_and_schedule: upserted {n1} rows")

    n2 = upsert_table2(conn, args.table2)
    print(f"spend_history: upserted {n2} rows")

    conn.close()


if __name__ == "__main__":
    main()
