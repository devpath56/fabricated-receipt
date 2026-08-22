"""
Check 1 -- "is this invoice complete enough to check?"

It runs FIRST and it GATES. If the document cannot be trusted as an invoice,
checks 2, 3 and 4 do not run at all -- and, critically, they are reported as
NOT RUN rather than as passed.

That distinction is the whole point. A pipeline that lets a bad extraction
through reads:

    bad PDF -> garbage fields -> vendor "matched" -> no duplicate found -> APPROVE

Every downstream check answered a question about a document nobody read. The
answers are not wrong so much as meaningless, and the confidence number built
from them is the fabricated receipt this project is named after.

OUTCOME VOCABULARY matches screens/check-1-intake.html: Approve / Comment.
Intake never DENIES -- a missing field is not evidence of fraud, it is the
absence of evidence, so it can only ever be a COMMENT.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# The fields every later check depends on, and which check needs each one.
# po_id is included because checks 3 and 4 are BOTH keyed on it: without it
# the duplicate search has nothing to match and the ERP lookup has nothing to
# look up. The operator's original list of four omitted it.
REQUIRED = (
    ("invoice_id",  "invoice number",  "check 3 keys the duplicate search on it"),
    ("vendor_name", "vendor",          "check 2 resolves it to a canonical vendor"),
    ("amount",      "invoice amount",  "check 3 matches on PO + amount + period"),
    ("date",        "invoice date",    "the period is derived from it"),
    ("po_id",       "purchase order",  "checks 3 and 4 are both keyed on it"),
)


@dataclass
class IntakeResult:
    check: str
    applicable: bool
    outcome: str                       # APPROVE | COMMENT
    reason: str
    missing: list = field(default_factory=list)
    present_count: int = 0
    required_count: int = 0


def _is_missing(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def run_intake_check(fields: dict) -> IntakeResult:
    """
    NEVER RAISES. A malformed or absent field dict is itself an intake failure,
    which is the answer, not an exception.
    """
    f = fields or {}

    missing = [
        {"field": key, "label": label, "why": why}
        for key, label, why in REQUIRED
        if _is_missing(f.get(key))
    ]

    present = len(REQUIRED) - len(missing)

    if not missing:
        return IntakeResult(
            check="intake",
            applicable=True,
            outcome="APPROVE",
            reason=f"{present} / {len(REQUIRED)} required fields present",
            missing=[],
            present_count=present,
            required_count=len(REQUIRED),
        )

    names = ", ".join(m["label"] for m in missing)
    return IntakeResult(
        check="intake",
        applicable=True,
        outcome="COMMENT",
        reason=(
            f"{present} / {len(REQUIRED)} required fields present — "
            f"{names} could not be read from the document. "
            f"The later checks were NOT RUN, because each one needs a field "
            f"that is absent."
        ),
        missing=missing,
        present_count=present,
        required_count=len(REQUIRED),
    )
