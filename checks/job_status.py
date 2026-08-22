"""
Check 1 — Job Status
Is this invoice's fms_id tied to a currently valid/active project?

Reads the LATEST reporting_period snapshot for the fms_id in
budget_and_schedule (Table 1) and fails if current_phase is terminal
(Completed / Rescinded / Cancelled) or if the fms_id doesn't exist at all.
"""
import sqlite3

TERMINAL_PHASES = {"Completed", "Rescinded", "Cancelled"}


def check_job_status(conn: sqlite3.Connection, fms_id: str) -> dict:
    row = conn.execute(
        """
        SELECT b.fms_id, b.current_phase, b.fms_project_name,
               b.total_budget, b.reporting_period
        FROM budget_and_schedule b
        JOIN (
            SELECT fms_id, MAX(reporting_period) AS maxp
            FROM budget_and_schedule
            WHERE fms_id = ?
            GROUP BY fms_id
        ) latest ON latest.fms_id = b.fms_id AND latest.maxp = b.reporting_period
        """,
        (fms_id,),
    ).fetchone()

    if row is None:
        return {
            "check": "job_status",
            "passed": False,
            "reason": f"fms_id '{fms_id}' was not found in Table 1 at all.",
        }

    phase = row["current_phase"]
    if phase in TERMINAL_PHASES:
        return {
            "check": "job_status",
            "passed": False,
            "reason": (
                f"Project '{row['fms_project_name']}' (fms_id {fms_id}) has "
                f"current_phase = {phase} as of reporting_period "
                f"{row['reporting_period']} — not eligible for new invoices."
            ),
            "current_phase": phase,
            "reporting_period": row["reporting_period"],
        }

    return {
        "check": "job_status",
        "passed": True,
        "reason": (
            f"Project '{row['fms_project_name']}' (fms_id {fms_id}) is in "
            f"phase '{phase}' as of {row['reporting_period']} — active."
        ),
        "current_phase": phase,
        "reporting_period": row["reporting_period"],
        "total_budget": row["total_budget"],
    }
