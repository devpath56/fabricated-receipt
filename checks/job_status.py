"""
Check 4 -- "is the job behind this PO still live?"

Reads data/erp.csv only. Nothing generated: current_phase, pid and
agency_project_name are all real NYC columns from fb86-vt7u.

THREE OUTCOMES, and the difference between two of them is the whole point:

    DENY     a check RAN and FAILED.     applicable=True.  Counts in the denominator.
    COMMENT  a check COULD NOT RUN.      applicable=False. LEAVES the denominator.
    APPROVE  a check ran and passed.     applicable=True.

confidence = checks passed / checks applicable. A COMMENT that counted as a
failure would make "I could not tell" indistinguishable from "the job is dead",
and those are different facts an approver acts on differently.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# THE DEAD SET -- 8 words, not 2.
#
# data/erp.csv currently marks job_open_for_charges=false on exactly 502 rows:
# (Completed) 394 + (Cancelled) 108. Measured against this same file, the full
# dead vocabulary catches 15 MORE fms_ids -- Terminated, Defaulted, Withdrawn
# among them, e.g. F175MCE91, F1FTRENOV, HBM246350, P-102BRPP, P-1TRAILW.
#
# The 15 matter qualitatively, not financially: a gate whose dead set omits
# Defaulted scores PAYING A CONTRACTOR IN DEFAULT as a correct answer.
# Rescinded / Defunded / Funding Withdrawn carry 0 rows in this snapshot but
# appear in earlier reporting periods, which is why they are listed.
# ---------------------------------------------------------------------------
DEAD_PHASES = frozenset({
    "completed", "cancelled", "terminated", "defaulted",
    "withdrawn", "rescinded", "defunded", "funding withdrawn",
})

# Statuses NYC records and defines NOWHERE. Not dead, not established as live.
# (Pending) alone is 21.5% of all rows across the 10 reporting periods.
UNRULED_PHASES = frozenset({
    "pending", "partner-managed", "requirements contract", "pass-through fund",
    "lump sum", "equipment", "design built", "design build", "funding agreement",
    "job order contract", "consultant services", "initiation", "it project",
    "real estate transaction", "land acquisition", "land purchase",
    "property acquisition", "ifa", "fundraising", "pre-lease",
    "scope development", "pre-construction phase", "security project",
    "transferred", "fmsid changed", "project renamed", "capitally ineligible",
    "non capital fund", "expense", "n/a", "overall misc",
})

HELD_PHASES = frozenset({"on-hold", "on hold", "inactive", "holding code", "not fully funded"})

# The five real construction phases. Everything else is not a phase.
LIVE_PHASES = frozenset({"pre-design", "design", "construction procurement", "construction", "close-out", "closeout"})

# OPERATOR RULING PENDING -- is a held job a DENY or a COMMENT?
# Ships COMMENT: a hold is temporary and reversible, so "cannot currently be
# approved" is truer than "this check failed". One line to reverse.
HELD_OUTCOME = "COMMENT"


def norm_phase(raw: str | None) -> str:
    """Strip brackets and case. Required for the dead match, NOT for evidence."""
    return re.sub(r"[()]", "", str(raw or "")).strip().lower()


def is_dead(raw: str | None) -> bool:
    return norm_phase(raw) in DEAD_PHASES


def _liveness(raw: str | None) -> str:
    n = norm_phase(raw)
    if n in DEAD_PHASES:
        return "dead"
    if n in LIVE_PHASES:
        return "live"
    return "unknown"          # HELD, UNRULED, or not in the contract at all


@dataclass
class JobStatusResult:
    check: str
    po_id: str | None
    applicable: bool
    outcome: str              # APPROVE | COMMENT | DENY
    reason: str
    rows: list = field(default_factory=list)


def _has_agency_record(row) -> bool:
    """
    Two columns, not three. current_phase_start was tried and rejected: it is
    NULL on 100% of Pre-Design and Close-out rows, so requiring it would mark
    43% of legitimate rows unverifiable.
    """
    return bool(str(getattr(row, "pid", "") or "").strip()) and \
           bool(str(getattr(row, "agency_project_name", "") or "").strip())


def check_job_status(po_id: str | None, erp_rows: list) -> JobStatusResult:
    """
    NEVER RAISES. Every failure mode is an outcome.

    Branch order is load-bearing and each position was measured:
      1 orphan        -- the PO resolves to nothing
      2 DEAD          -- tested BEFORE any disagreement logic. One dead record
                         blocks the charge even when live siblings outnumber it;
                         a live sibling does not make cancelled work billable.
      3 held          -- tested BEFORE evidence, so the operator switch reaches
                         every held PO rather than only those that happen to
                         carry an agency record.
      4 unruled       -- NYC defines the word nowhere; payability is withheld.
      5 no evidence   -- nothing to verify the work against.
      6 APPROVE
    """
    rows = list(erp_rows or [])

    if not rows:
        return JobStatusResult("job_status", po_id, False, "COMMENT",
                               f"no ERP record found for PO {po_id!r} — the check could not run", [])

    livenesses = {_liveness(getattr(r, "current_phase", None)) for r in rows}

    if "dead" in livenesses:
        dead_rows = [r for r in rows if is_dead(getattr(r, "current_phase", None))]
        which = ", ".join(sorted({r.current_phase for r in dead_rows}))
        if len(livenesses) > 1:
            detail = "; ".join(f"pid {r.pid or 'null'} is {r.current_phase}" for r in rows)
            reason = (f"{len(dead_rows)} of {len(rows)} project records on this PO are {which} — "
                      f"{detail}. A dead record on the PO blocks the charge regardless of the others.")
        else:
            reason = f"the job is {which} — it no longer accepts charges"
        return JobStatusResult("job_status", po_id, True, "DENY", reason, rows)

    held = [r for r in rows if norm_phase(getattr(r, "current_phase", None)) in HELD_PHASES]
    if held:
        return JobStatusResult("job_status", po_id, HELD_OUTCOME == "DENY", HELD_OUTCOME,
                               f"the job is on hold ({held[0].current_phase}) — not currently billable", rows)

    unruled = [r for r in rows if norm_phase(getattr(r, "current_phase", None)) in UNRULED_PHASES]
    if unruled:
        return JobStatusResult("job_status", po_id, False, "COMMENT",
                               f"status {unruled[0].current_phase!r} is recorded but NYC defines it "
                               f"nowhere — payability is unruled, so the check could not run", rows)

    if "unknown" in livenesses:
        bad = next(r for r in rows if _liveness(getattr(r, "current_phase", None)) == "unknown")
        return JobStatusResult("job_status", po_id, False, "COMMENT",
                               f"status {bad.current_phase!r} is not in the contract — "
                               f"the check could not run", rows)

    no_record = [r for r in rows if not _has_agency_record(r)]
    if no_record:
        return JobStatusResult("job_status", po_id, False, "COMMENT",
                               f"no agency record on {len(no_record)} of {len(rows)} project record(s) — "
                               f"there is nothing to verify the work against, so the check could not run", rows)

    return JobStatusResult("job_status", po_id, True, "APPROVE",
                           f"the job is live ({rows[0].current_phase}) and carries an agency record", rows)
