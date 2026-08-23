from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path
from typing import Any

import streamlit as st
# mistralai 1.x exports Mistral at the TOP LEVEL. mistralai.client holds only
# MistralClient, the 0.x name -- so `from mistralai.client import Mistral`
# raises ImportError on every 1.x install, which requirements.txt pins.
from mistralai import Mistral

# ---------------------------------------------------------------------
# PATHS
# ---------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from checks.common import (  # noqa: E402
    Invoice,
    load_erp,
    load_invoices,
    load_vendors,
)

from checks.duplicate_payment import (  # noqa: E402
    find_duplicates,
    find_orphan_pos,
)

from checks.vendor_resolution import VendorResolver  # noqa: E402
from checks.job_status import check_job_status  # noqa: E402
from checks.intake import run_intake_check  # noqa: E402


# ---------------------------------------------------------------------
# PAGE CONFIG
# ---------------------------------------------------------------------

st.set_page_config(
    page_title="Redline",
    page_icon="🧾",
    layout="centered",
)


# ---------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------

st.markdown(
    """
    <style>

    .main {
        max-width: 900px;
        margin: auto;
    }

    .decision {
        padding: 28px;
        border-radius: 16px;
        text-align: center;
        margin: 20px 0;
        border: 1px solid rgba(128,128,128,.25);
    }

    .decision-clear {
        background: rgba(46, 160, 67, .10);
    }

    .decision-hold {
        background: rgba(230, 126, 34, .10);
    }

    .decision-title {
        font-size: 34px;
        font-weight: 800;
        margin-bottom: 5px;
    }

    .decision-subtitle {
        font-size: 16px;
        opacity: .8;
    }

    .check-card {
        border: 1px solid rgba(128,128,128,.25);
        border-radius: 12px;
        padding: 18px;
        margin: 10px 0;
    }

    .pass {
        color: #2e8b57;
        font-weight: 700;
    }

    .fail {
        color: #d64545;
        font-weight: 700;
    }

    .warning {
        color: #d97706;
        font-weight: 700;
    }

    .small {
        font-size: 13px;
        opacity: .7;
    }

    .dim {
        opacity: .55;
        font-weight: 500;
    }

    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------
# HEADER
# ---------------------------------------------------------------------

st.title("🧾 Redline")

st.caption(
    "Upload an incoming invoice. Mistral OCR extracts the invoice data, "
    "deterministic checks produce the authoritative decision, and Mistral "
    "can answer natural-language questions about the evidence."
)


# ---------------------------------------------------------------------
# MISTRAL CLIENT
# ---------------------------------------------------------------------

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")

# The key is needed ONLY for OCR on an uploaded PDF. st.stop() here killed the
# whole app, including the three checks -- which read data/erp.csv, data/
# vendors.csv and data/invoices.csv and need no network at all. The gate now
# fires where OCR is actually attempted, so a reviewer without a key can still
# exercise vendor resolution, duplicate payment and job status.
if MISTRAL_API_KEY:
    mistral_client = Mistral(api_key=MISTRAL_API_KEY)
else:
    mistral_client = None
    st.warning(
        "MISTRAL_API_KEY is not set, so PDF upload and invoice chat are disabled. "
        "Type a po_id instead — the offline verification checks can still run."
    )


# ---------------------------------------------------------------------
# REFERENCE DATA
# ---------------------------------------------------------------------

@st.cache_resource
def load_reference_data():

    vendors = load_vendors()
    invoices = load_invoices()
    erp = load_erp()

    resolver = VendorResolver(vendors)

    valid_fms_ids = {
        row.fms_id
        for row in erp
    }

    # check 4 needs the ROWS, not just the id set: one fms_id can carry
    # several project records and they do not always agree.
    erp_by_fms: dict[str, list] = {}
    for row in erp:
        erp_by_fms.setdefault(
            row.fms_id,
            [],
        ).append(row)

    # Typing a po_id must find the REAL invoice sitting on that PO. Without
    # this index the fallback had nothing to look up and supplied a
    # placeholder vendor and amount instead -- three checks answering
    # questions about an invoice nobody submitted.
    invoices_by_po: dict[str, list] = {}
    for inv in invoices:
        invoices_by_po.setdefault(
            inv.po_id,
            [],
        ).append(inv)

    return (
        resolver,
        invoices,
        valid_fms_ids,
        erp_by_fms,
        invoices_by_po,
    )


try:

    (
        resolver,
        existing_invoices,
        valid_fms_ids,
        erp_by_fms,
        invoices_by_po,
    ) = load_reference_data()

except Exception as exc:

    st.error(
        "Could not load the repository reference data."
    )

    st.exception(exc)

    st.stop()


# ---------------------------------------------------------------------
# SESSION STATE
# ---------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state.messages = []

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "invoice_context" not in st.session_state:
    st.session_state.invoice_context = None


# ---------------------------------------------------------------------
# GROUNDED MISTRAL CHAT
# ---------------------------------------------------------------------

CHAT_MODEL = "mistral-small-latest"

LLM_SYSTEM_PROMPT = """
You are the conversational assistant for an invoice verification system.

Answer questions about the CURRENT invoice using ONLY the supplied invoice
fields, OCR evidence, and deterministic verification results.

Rules:
1. The deterministic verification decision is authoritative.
2. Never change, override, or invent the decision.
3. Never claim a check passed if the evidence says it failed or was not run.
4. If intake failed and downstream checks were not run, say so explicitly.
5. Never invent missing invoice information.
6. If evidence is insufficient, say so instead of guessing.
7. Distinguish what the document says from what verification established.
8. Keep answers concise and practical.
"""


def _intake_context(intake):
    if intake is None:
        return None
    return {
        "outcome": getattr(intake, "outcome", None),
        "reason": getattr(intake, "reason", None),
        "present_count": getattr(intake, "present_count", None),
        "required_count": getattr(intake, "required_count", None),
        "missing": getattr(intake, "missing", None),
    }


def _job_context(job_status):
    if job_status is None:
        return None
    rows = []
    for row in (job_status.get("rows") or []):
        rows.append({
            "pid": getattr(row, "pid", None),
            "current_phase": getattr(row, "current_phase", None),
            "agency_project_name": getattr(row, "agency_project_name", None),
        })
    return {
        "passed": job_status.get("passed"),
        "applicable": job_status.get("applicable"),
        "outcome": job_status.get("outcome"),
        "reason": job_status.get("reason"),
        "rows": rows,
    }


def build_invoice_llm_context(result: dict) -> dict:
    """Build the read-only evidence package supplied to Mistral chat."""
    fields = result.get("fields") or {}
    invoice = result.get("invoice")
    invoice_context = None
    if invoice is not None:
        invoice_context = {
            "invoice_id": getattr(invoice, "invoice_id", None),
            "po_id": getattr(invoice, "po_id", None),
            "vendor_name": getattr(invoice, "vendor_name", None),
            "amount": getattr(invoice, "amount", None),
            "period": getattr(invoice, "period", None),
            "submitted_at": getattr(invoice, "submitted_at", None),
        }
    # A null check in this payload must not read to the model as "nothing
    # to report". Name the checks that never ran, so the chat cannot round
    # a missing result up into a pass.
    not_run = [
        name
        for name, value in (
            ("intake_check", result.get("intake")),
            ("vendor_check", result.get("vendor")),
            ("payment_duplication_check", result.get("duplicate")),
            ("job_status_check", result.get("job_status")),
        )
        if value is None
    ]

    return {
        "mode": result.get("mode"),
        "po_id": result.get("po_id"),
        "invoice": invoice_context,
        "checks_not_run": not_run,
        "checks_not_run_note": (
            "These checks had no input and were never attempted. They are "
            "absent from the confidence denominator. Do not describe them "
            "as passed, clean or clear -- say they could not run."
        ),
        "extracted_fields": {
            k: v for k, v in fields.items() if k != "raw_text"
        },
        "intake_check": _intake_context(result.get("intake")),
        "vendor_check": result.get("vendor"),
        "payment_duplication_check": result.get("duplicate"),
        "job_status_check": _job_context(result.get("job_status")),
        "decision": result.get("decision"),
        "confidence": result.get("confidence"),
        "passed_count": result.get("passed_count"),
        "applicable_count": result.get("applicable_count"),
        "ocr_text": (fields.get("raw_text") or "")[:12000],
    }


def ask_mistral_about_invoice(question: str) -> str:
    """Answer using current invoice evidence plus prior chat turns."""
    if mistral_client is None:
        return "MISTRAL_API_KEY is not set, so invoice chat is unavailable."
    if st.session_state.invoice_context is None:
        return "Please upload an invoice PDF first so I have a verified invoice context."

    context_json = json.dumps(
        st.session_state.invoice_context,
        indent=2,
        default=str,
    )

    messages = [
        {"role": "system", "content": LLM_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": "CURRENT INVOICE EVIDENCE PACKAGE:\n\n" + context_json,
        },
        {
            "role": "assistant",
            "content": "I will answer using only the supplied invoice evidence and deterministic verification results.",
        },
    ]
    messages.extend(st.session_state.chat_history[-10:])
    messages.append({"role": "user", "content": question})

    response = mistral_client.chat.complete(
        model=CHAT_MODEL,
        messages=messages,
    )
    return str(response.choices[0].message.content)


# ---------------------------------------------------------------------
# MISTRAL OCR / DOCUMENT EXTRACTION
# ---------------------------------------------------------------------

INVOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "invoice_id": {
            "type": ["string", "null"],
            "description": (
                "The invoice number or invoice identifier. "
                "Look anywhere in the document. "
                "Return null if not present."
            ),
        },
        "vendor_name": {
            "type": ["string", "null"],
            "description": (
                "The legal/business name of the company or supplier "
                "issuing the invoice. Do not return the customer/bill-to "
                "company. Look at the invoice header, supplier section, "
                "from section, remittance section, or seller information."
            ),
        },
        "vendor_address": {
            "type": ["string", "null"],
            "description": (
                "The address of the company issuing the invoice. "
                "Return null if not available."
            ),
        },
        "po_id": {
            "type": ["string", "null"],
            "description": (
                "The purchase order number associated with the invoice. "
                "Look for PO, purchase order, PO number, or similar. "
                "Return null if not present."
            ),
        },
        "amount": {
            "type": ["number", "null"],
            "description": (
                "The final total amount due on the invoice. "
                "Use the grand total, total due, amount due, or equivalent. "
                "Do not use subtotal or tax unless that is the final amount."
            ),
        },
        "currency": {
            "type": ["string", "null"],
            "description": (
                "The invoice currency, such as USD, EUR, or GBP. "
                "Return null if it cannot be determined."
            ),
        },
        "invoice_date": {
            "type": ["string", "null"],
            "description": (
                "The invoice date. Return it as YYYY-MM-DD when possible. "
                "Return null if not present."
            ),
        },
        "payment_terms": {
            "type": ["string", "null"],
            "description": (
                "Payment terms such as Net 30, Net 45, Due on receipt. "
                "Return null if not present."
            ),
        },
    },
    "required": [
        "invoice_id",
        "vendor_name",
        "vendor_address",
        "po_id",
        "amount",
        "currency",
        "invoice_date",
        "payment_terms",
    ],
    "additionalProperties": False,
}


def encode_pdf(uploaded_file) -> str:

    uploaded_file.seek(0)

    pdf_bytes = uploaded_file.read()

    return base64.b64encode(pdf_bytes).decode("utf-8")


def run_mistral_ocr(uploaded_file) -> tuple[dict[str, Any], str]:

    # The key gate lives HERE, at the only place that needs the network.
    # It used to st.stop() at import time, which took the three offline
    # checks down with it.
    if mistral_client is None:
        st.error(
            "MISTRAL_API_KEY is not set, so this PDF cannot be read. "
            "Type a po_id instead, or set the key and restart."
        )
        st.code(
            'export MISTRAL_API_KEY="..."',
            language="bash",
        )
        st.stop()

    base64_pdf = encode_pdf(uploaded_file)

    response = mistral_client.ocr.process(
        model="mistral-ocr-latest",
        pages=list(range(8)),
        document={
            "type": "document_url",
            "document_url": (
                f"data:application/pdf;base64,{base64_pdf}"
            ),
        },
        document_annotation_format={
            "type": "json_schema",
            "json_schema": {
                "name": "invoice",
                "schema_definition": INVOICE_SCHEMA,
                "strict": True,
            },
        },
        document_annotation_prompt=(
            "Extract the invoice fields from the entire document. "
            "Identify the company that issued/sent the invoice as "
            "vendor_name, not the bill-to/customer company. "
            "Use visual layout, headers, tables, and document context. "
            "Do not guess values that are not present. "
            "For amount, return the final amount due or grand total."
        ),
        include_image_base64=False,
        # include_blocks and confidence_scores_granularity are NOT parameters of
        # Ocr.process in mistralai 1.12.4 -- the version requirements.txt pins.
        # Passing them raised TypeError on every upload. Accepted kwargs are:
        # model, document, id, pages, include_image_base64, image_limit,
        # image_min_size, bbox_annotation_format, document_annotation_format,
        # document_annotation_prompt, table_format, extract_header,
        # extract_footer, retries, server_url, timeout_ms, http_headers.
        extract_header=True,
        extract_footer=True,
        table_format="html",
    )

    # Structured annotation
    annotation_raw = response.document_annotation

    if not annotation_raw:
        raise RuntimeError(
            "Mistral OCR did not return structured invoice data."
        )

    if isinstance(annotation_raw, str):
        extracted = json.loads(annotation_raw)
    else:
        extracted = annotation_raw

    # OCR markdown
    pages = getattr(response, "pages", []) or []

    markdown_parts = []

    for page in pages:
        markdown = getattr(page, "markdown", None)

        if markdown:
            markdown_parts.append(markdown)

    raw_text = "\n\n".join(markdown_parts)

    return extracted, raw_text


# ---------------------------------------------------------------------
# NORMALIZE EXTRACTED DATA
# ---------------------------------------------------------------------

def normalize_amount(value: Any) -> float | None:

    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = (
        str(value)
        .replace("$", "")
        .replace(",", "")
        .replace("USD", "")
        .strip()
    )

    try:
        return float(text)

    except ValueError:
        return None


def normalize_period(date_value: str | None) -> str:

    if not date_value:
        from datetime import datetime

        return datetime.now().strftime("%Y%m")

    # Expected output is normally YYYY-MM-DD.
    parts = date_value.split("-")

    if len(parts) >= 2 and len(parts[0]) == 4:

        year = parts[0]
        month = parts[1]

        if month.isdigit():

            month_num = int(month)

            if 1 <= month_num <= 12:
                return f"{year}{month_num:02d}"

    # Fallback for other common formats.
    import re

    digits = re.findall(r"\d+", date_value)

    year = None
    month = None

    for item in digits:

        if len(item) == 4:
            year = item

    if year:

        for item in digits:

            if len(item) <= 2:

                number = int(item)

                if 1 <= number <= 12:
                    month = f"{number:02d}"
                    break

    if year and month:
        return f"{year}{month}"

    from datetime import datetime

    return datetime.now().strftime("%Y%m")


def normalize_invoice_fields(
    extracted: dict[str, Any],
    raw_text: str,
) -> dict[str, Any]:

    return {
        "invoice_id": extracted.get("invoice_id"),
        "vendor_name": extracted.get("vendor_name"),
        "vendor_address": extracted.get("vendor_address"),
        "po_id": extracted.get("po_id"),
        "amount": normalize_amount(
            extracted.get("amount")
        ),
        "currency": extracted.get("currency"),
        "date": extracted.get("invoice_date"),
        "period": normalize_period(
            extracted.get("invoice_date")
        ),
        "payment_terms": extracted.get("payment_terms"),
        "raw_text": raw_text,
    }


# ---------------------------------------------------------------------
# VALIDATION
# ---------------------------------------------------------------------

def validate_invoice(
    fields: dict[str, Any],
) -> list[str]:

    errors = []

    if not fields.get("invoice_id"):
        errors.append(
            "Mistral OCR could not identify an invoice number."
        )

    if not fields.get("vendor_name"):
        errors.append(
            "Mistral OCR could not identify the invoice vendor."
        )

    if not fields.get("po_id"):
        errors.append(
            "Mistral OCR could not identify a purchase order number."
        )

    if fields.get("amount") is None:
        errors.append(
            "Mistral OCR could not identify the final invoice amount."
        )

    return errors


# ---------------------------------------------------------------------
# CONVERT TO REPO INVOICE MODEL
# ---------------------------------------------------------------------

def make_invoice(
    fields: dict[str, Any],
) -> Invoice:

    return Invoice(
        invoice_id=fields["invoice_id"],
        po_id=fields["po_id"],
        vendor_id="",
        vendor_name=fields["vendor_name"],
        amount=float(fields["amount"]),
        period=str(fields["period"]),
        status="pending",
        submitted_at=fields.get("date") or "",
        doc_uri="",
        missing_field="none",
        label_is_duplicate=False,
        label_dead_job=False,
    )


# ---------------------------------------------------------------------
# RUN VENDOR CHECK
# ---------------------------------------------------------------------

def run_vendor_check(
    invoice: Invoice,
):

    result = resolver.resolve(
        invoice.vendor_name
    )

    passed = (
        result.status == "merged"
    )

    return {
        "passed": passed,
        "status": result.status,
        "vendor_id": getattr(
            result,
            "vendor_id",
            None,
        ),
        "canonical_name": getattr(
            result,
            "canonical_name",
            None,
        ),
        "method": getattr(
            result,
            "method",
            None,
        ),
        "score": getattr(
            result,
            "score",
            0.0,
        ),
    }


# ---------------------------------------------------------------------
# RUN DUPLICATE CHECK
# ---------------------------------------------------------------------

def run_duplicate_check(
    invoice: Invoice,
):

    # Check whether PO exists
    orphans = set(
        find_orphan_pos(
            [invoice],
            valid_fms_ids,
        )
    )

    is_orphan = (
        invoice.invoice_id in orphans
    )

    # Compare against historical invoices.
    #
    # A row read straight out of the ledger is still IN that ledger, so
    # comparing it against the unfiltered history matches it against
    # itself -- same vendor, same amount, same period, same po_id, scored
    # as an exact duplicate. Drop the row under test before comparing.
    history = [
        row
        for row in existing_invoices
        if row.invoice_id != invoice.invoice_id
    ]

    combined = (
        history
        + [invoice]
    )

    findings = find_duplicates(
        combined,
        resolver,
    )

    duplicate = next(
        (
            finding
            for finding in findings
            if finding.invoice_id
            == invoice.invoice_id
        ),
        None,
    )

    passed = (
        not is_orphan
        and duplicate is None
    )

    return {
        "passed": passed,
        "is_orphan": is_orphan,
        "duplicate": duplicate,
        "history_count": len(history),
    }


# ---------------------------------------------------------------------
# RUN JOB STATUS CHECK
# ---------------------------------------------------------------------

def run_job_status_check(
    invoice: Invoice,
):

    result = check_job_status(
        invoice.po_id,
        erp_by_fms.get(
            invoice.po_id,
            [],
        ),
    )

    return {
        "passed": result.outcome == "APPROVE",
        "applicable": result.applicable,
        "outcome": result.outcome,
        "reason": result.reason,
        "rows": result.rows,
    }


# ---------------------------------------------------------------------
# DECISION
# ---------------------------------------------------------------------

def make_decision(
    vendor_result: dict,
    duplicate_result: dict,
    job_result: dict,
) -> str:
    """
    APPROVE / COMMENT / DENY -- the same three words as
    screens/check-4-job-status.html.

    DENY     a check RAN and FAILED. The job no longer accepts charges.
             applicable=True, so it counts against confidence.
    COMMENT  a check COULD NOT RUN, or a soft check failed. An unruled
             status, a hold and a missing agency record all land here:
             none means "no", they mean "not established". A COMMENT
             LEAVES the confidence denominator.
    APPROVE  every applicable check ran and passed.

    Collapsing DENY into COMMENT tells a reviewer that a cancelled job and
    an undefined status are the same fact. Measured on data/erp.csv:
    512 POs are dead; 2,096 are merely unestablished.
    """

    if job_result["outcome"] == "DENY":
        return "DENY"

    if (
        vendor_result["passed"]
        and duplicate_result["passed"]
        and job_result["outcome"] == "APPROVE"
    ):

        return "APPROVE"

    return "COMMENT"


# ---------------------------------------------------------------------
# RESULT OBJECT
# ---------------------------------------------------------------------

def run_invoice_checks(
    fields: dict[str, Any],
    invoice: Invoice | None = None,
):
    """
    `invoice` is supplied when the row came out of data/invoices.csv rather
    than out of OCR. Passing it through keeps the ledger's own status --
    make_invoice() hardcodes status="pending", which would silently turn an
    already-paid invoice into a pending one and change what check 3 does
    with it (block vs clawback).
    """

    # ---- CHECK 1 GATES EVERYTHING ---------------------------------------
    # If the document cannot be trusted as an invoice, the later checks are
    # NOT RUN -- not "passed". Running them on garbage fields produces three
    # confident answers about a document nobody read, which is exactly the
    # fabricated receipt this product exists to catch.
    intake = run_intake_check(fields)

    if intake.outcome != "APPROVE":

        return {
            "mode": "invoice",
            "invoice": None,
            "fields": fields,
            "intake": intake,
            "vendor": None,
            "duplicate": None,
            "job_status": None,
            "decision": "COMMENT",
            # Only intake was applicable. It ran and did not pass, so the
            # score is 0/1 -- NOT 0/4, which would imply three checks ran
            # and failed.
            "confidence": 0.0,
            "passed_count": 0,
            "applicable_count": 1,
        }

    if invoice is None:
        invoice = make_invoice(
            fields
        )

    vendor_result = run_vendor_check(
        invoice
    )

    duplicate_result = run_duplicate_check(
        invoice
    )

    job_result = run_job_status_check(
        invoice
    )

    decision = make_decision(
        vendor_result,
        duplicate_result,
        job_result,
    )

    # confidence = passed / applicable. A check that COULD NOT RUN leaves
    # the denominator: never scored as a pass, never as a failure.
    applicable = [
        True,                              # intake ran and passed
        vendor_result["passed"],
        duplicate_result["passed"],
    ]
    if job_result["applicable"]:
        applicable.append(
            job_result["passed"]
        )

    passed_count = sum(
        1 for a in applicable if a
    )

    return {
        "mode": "invoice",
        "invoice": invoice,
        "fields": fields,
        "intake": intake,
        "vendor": vendor_result,
        "duplicate": duplicate_result,
        "job_status": job_result,
        "decision": decision,
        "confidence": (
            passed_count / len(applicable)
            if applicable
            else None
        ),
        "passed_count": passed_count,
        "applicable_count": len(applicable),
    }


def run_po_lookup(
    po_id: str,
) -> dict:
    """
    A po_id that exists in the ERP but carries no invoice in
    data/invoices.csv.

    There is no document to intake, no vendor string to resolve and no
    payment to compare against, so checks 1, 2 and 3 are NOT RUN. Handing
    them a placeholder vendor and amount so that they have something to
    grade is precisely the fabricated receipt this product exists to catch:
    confident verdicts about an invoice nobody submitted.

    Check 4 is the only check whose sole input IS the po_id, so it is the
    only one that can answer here.
    """

    result = check_job_status(
        po_id,
        erp_by_fms.get(
            po_id,
            [],
        ),
    )

    job = {
        "passed": result.outcome == "APPROVE",
        "applicable": result.applicable,
        "outcome": result.outcome,
        "reason": result.reason,
        "rows": result.rows,
    }

    # Only check 4 was ever applicable. A check that could not run leaves
    # the denominator -- it is never scored as a pass.
    applicable = (
        [job["passed"]]
        if job["applicable"]
        else []
    )

    passed_count = sum(
        1 for a in applicable if a
    )

    # A live job is NOT an approval. Three of the four checks never ran, so
    # nothing here establishes that this PO may be paid -- only that the
    # job behind it is not dead. That is a COMMENT, not an APPROVE.
    decision = (
        "DENY"
        if job["outcome"] == "DENY"
        else "COMMENT"
    )

    return {
        "mode": "po_only",
        "po_id": po_id,
        "invoice": None,
        "fields": {},
        "intake": None,
        "vendor": None,
        "duplicate": None,
        "job_status": job,
        "decision": decision,
        "confidence": (
            passed_count / len(applicable)
            if applicable
            else None
        ),
        "passed_count": passed_count,
        "applicable_count": len(applicable),
    }


def render_job_status_card(
    job_status: dict,
):
    """check 4 evidence. Shared by the invoice path and the PO-only path."""

    st.markdown(
        '<div class="check-card">',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="check-title">Job status</div>',
        unsafe_allow_html=True,
    )
    st.caption("Is the job behind this PO still live?")

    if job_status["outcome"] == "APPROVE":
        st.markdown(
            '<span class="pass">✓ job open for charges</span>',
            unsafe_allow_html=True,
        )
    elif job_status["outcome"] == "DENY":
        st.markdown(
            '<span class="fail">✕ job is dead</span>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<span class="warning">⚠ could not establish</span>',
            unsafe_allow_html=True,
        )

    st.write(job_status["reason"])

    if job_status["rows"]:
        st.caption(
            f"the {len(job_status['rows'])} ERP row(s) this was read from:"
        )
        st.dataframe(
            [
                {
                    "pid": row.pid or "(null)",
                    "current_phase": row.current_phase,
                    "agency_project_name": (
                        row.agency_project_name or "(none)"
                    ),
                }
                for row in job_status["rows"]
            ],
            hide_index=True,
            width="stretch",
        )

    st.markdown(
        "</div>",
        unsafe_allow_html=True,
    )



# ---------------------------------------------------------------------
# RENDER RESULT
# ---------------------------------------------------------------------

def render_po_lookup(
    result: dict,
):
    """
    A PO with no invoice behind it. Three checks had no input, so they are
    shown as NOT RUN rather than left blank -- an empty space reads as
    "fine", and a green tick would be a lie.
    """

    job_status = result["job_status"]

    st.markdown(
        f"### PO `{result['po_id']}`"
    )
    st.caption(
        "No invoice in data/invoices.csv carries this PO, so there is no "
        "document to check — only the job behind it."
    )

    st.divider()

    for n, name, why in (
        (1, "Intake check",
         "no document was submitted, so there were no fields to read"),
        (2, "Vendor entity check",
         "no invoice means no vendor string to resolve"),
        (3, "Payment duplication check",
         "no invoice means no amount or period to match on"),
    ):
        st.markdown(f"#### {n}. {name}")
        st.markdown(
            '<span class="dim">— NOT RUN</span>',
            unsafe_allow_html=True,
        )
        st.caption(why)

    st.divider()

    st.markdown("#### 4. Job status check")
    render_job_status_card(job_status)

    if result["decision"] == "DENY":
        st.markdown(
            f"""
            <div class="decision decision-block">
                <div class="decision-title">✕ DENY</div>
                <div class="decision-subtitle">
                    {job_status["reason"]}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <div class="decision decision-hold">
                <div class="decision-title">⚠ COMMENT</div>
                <div class="decision-subtitle">
                    Only the job status could be checked. Nothing here
                    establishes that this PO may be paid.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if result["confidence"] is not None:
        st.caption(
            f"confidence = {result['passed_count']}/"
            f"{result['applicable_count']} = "
            f"{result['confidence']:.2f}   ·   checks 1–3 had no input, so "
            "they are absent from the denominator rather than counted as "
            "passes"
        )
    else:
        st.caption(
            "confidence = n/a   ·   no check could run on this PO, so there "
            "is nothing to score"
        )


def render_result(
    result: dict,
):

    if result.get("mode") == "po_only":
        render_po_lookup(result)
        return

    intake = result["intake"]

    # ---- CHECK 1 -------------------------------------------------------
    st.markdown("#### 1. Intake check")
    st.caption("Is this invoice complete enough to check?")

    if intake.outcome == "APPROVE":
        st.markdown(
            f'<span class="pass">✓ {intake.present_count} / '
            f'{intake.required_count} fields present</span>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<span class="warning">⚠ {intake.present_count} / '
            f'{intake.required_count} fields present</span>',
            unsafe_allow_html=True,
        )

    st.write(intake.reason)

    if intake.missing:
        st.dataframe(
            [
                {
                    "missing field": m["label"],
                    "what needed it": m["why"],
                }
                for m in intake.missing
            ],
            hide_index=True,
            width="stretch",
        )

        # Downstream checks are NOT RUN. Saying so is the point -- a blank
        # space would read as "fine", and a green tick would be a lie.
        st.divider()
        for n, name in (
            (2, "Vendor entity check"),
            (3, "Payment duplication check"),
            (4, "Job status check"),
        ):
            st.markdown(f"#### {n}. {name}")
            st.markdown(
                '<span class="dim">— NOT RUN</span>',
                unsafe_allow_html=True,
            )
            st.caption("intake did not pass, so this check was never attempted")

        st.divider()
        st.markdown(
            """
            <div class="decision decision-hold">
                <div class="decision-title">⚠ COMMENT</div>
                <div class="decision-subtitle">
                    The document could not be treated as a complete invoice.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption(
            f"confidence = {result['passed_count']}/"
            f"{result['applicable_count']} = "
            f"{result['confidence']:.2f}   ·   only intake was applicable; "
            "the other three were never attempted, so they are absent from "
            "the denominator rather than counted as failures"
        )
        return

    st.divider()

    invoice = result["invoice"]
    fields = result["fields"]

    vendor = result["vendor"]
    duplicate = result["duplicate"]

    decision = result["decision"]

    # -------------------------------------------------------------
    # Invoice details
    # -------------------------------------------------------------

    st.markdown(
        f"### Invoice `{invoice.invoice_id}`"
    )

    col1, col2 = st.columns(2)

    with col1:

        st.markdown(
            f"**Vendor**  \n"
            f"{invoice.vendor_name}"
        )

        st.markdown(
            f"**PO**  \n"
            f"{invoice.po_id}"
        )

    with col2:

        st.markdown(
            f"**Amount**  \n"
            f"${invoice.amount:,.2f}"
        )

        st.markdown(
            f"**Period**  \n"
            f"{invoice.period}"
        )

    st.divider()

    # -------------------------------------------------------------
    # Vendor check
    # -------------------------------------------------------------

    st.markdown(
        '<div class="check-card">',
        unsafe_allow_html=True,
    )

    st.markdown(
        "### 🏢 Vendor Entity Check"
    )

    if vendor["passed"]:

        st.markdown(
            '<span class="pass">✓ VERIFIED</span>',
            unsafe_allow_html=True,
        )

        st.write(
            f"**Invoice vendor:** "
            f"{invoice.vendor_name}"
        )

        st.write(
            f"**Matched vendor:** "
            f"{vendor['canonical_name']}"
        )

        st.write(
            f"**Vendor ID:** "
            f"`{vendor['vendor_id']}`"
        )

        st.write(
            f"**Resolution method:** "
            f"`{vendor['method']}`"
        )

        st.write(
            f"**Score:** "
            f"`{vendor['score']:.3f}`"
        )

    else:

        st.markdown(
            '<span class="fail">✕ NOT VERIFIED</span>',
            unsafe_allow_html=True,
        )

        st.write(
            f"Invoice vendor: "
            f"`{invoice.vendor_name}`"
        )

        st.write(
            f"Best match score: "
            f"`{vendor['score']:.3f}`"
        )

        st.write(
            "Vendor requires manual review."
        )

    st.markdown(
        "</div>",
        unsafe_allow_html=True,
    )

    # -------------------------------------------------------------
    # Duplicate check
    # -------------------------------------------------------------

    st.markdown(
        '<div class="check-card">',
        unsafe_allow_html=True,
    )

    st.markdown(
        "### 💳 Payment Duplication Check"
    )

    if duplicate["passed"]:

        st.markdown(
            '<span class="pass">✓ NO DUPLICATE FOUND</span>',
            unsafe_allow_html=True,
        )

        st.write(
            f"Checked against "
            f"**{duplicate['history_count']:,}** historical invoices."
        )

        st.write(
            "No matching payment was found."
        )

    else:

        if duplicate["is_orphan"]:

            st.markdown(
                '<span class="fail">✕ INVALID PO</span>',
                unsafe_allow_html=True,
            )

            st.write(
                f"PO `{invoice.po_id}` "
                "does not exist in the reference ERP data."
            )

        else:

            st.markdown(
                '<span class="fail">✕ DUPLICATE DETECTED</span>',
                unsafe_allow_html=True,
            )

            finding = duplicate["duplicate"]

            if finding:

                st.write(
                    f"**Duplicate type:** "
                    f"`{finding.kind}`"
                )

                st.write(
                    f"**Existing invoice:** "
                    f"`{finding.matched_invoice_id}`"
                )

    st.markdown(
        "</div>",
        unsafe_allow_html=True,
    )

    # -------------------------------------------------------------
    # Final decision
    # -------------------------------------------------------------

    st.divider()

    job_status = result["job_status"]

    render_job_status_card(job_status)

    # ---- the verdict -------------------------------------------------
    if decision == "APPROVE":

        st.markdown(
            """
            <div class="decision decision-clear">
                <div class="decision-title">✓ APPROVE</div>
                <div class="decision-subtitle">
                    Every applicable check ran and passed.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    elif decision == "DENY":

        st.markdown(
            f"""
            <div class="decision decision-block">
                <div class="decision-title">✕ DENY</div>
                <div class="decision-subtitle">
                    {job_status["reason"]}
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    else:

        st.markdown(
            """
            <div class="decision decision-hold">
                <div class="decision-title">⚠ COMMENT</div>
                <div class="decision-subtitle">
                    A check could not be evaluated. Manual review before payment.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    if result["confidence"] is not None:
        st.caption(
            f"confidence = {result['passed_count']}/"
            f"{result['applicable_count']} = "
            f"{result['confidence']:.2f}"
            + (
                ""
                if job_status["applicable"]
                else "   ·   job status could not run, so it LEAVES the "
                     "denominator — never scored as a pass, never as a failure"
            )
        )

    # -------------------------------------------------------------
    # Evidence
    # -------------------------------------------------------------

    with st.expander(
        "View Mistral extracted invoice data"
    ):

        st.json(
            {
                key: value
                for key, value in fields.items()
                if key != "raw_text"
            }
        )

    with st.expander(
        "View Mistral OCR text"
    ):

        st.text(
            fields.get(
                "raw_text",
                "(no OCR text — this invoice was not read from a PDF)",
            )
        )


# ---------------------------------------------------------------------
# CHAT HISTORY
#
# MOVED. This loop used to sit near the top of the file, ABOVE the
# definition of render_result -- so the first rerun that had a stored
# result raised NameError: name 'render_result' is not defined. Streamlit
# re-executes the whole module top to bottom on every interaction, so a
# replay loop must come AFTER the function it replays with.
# ---------------------------------------------------------------------

for message in st.session_state.messages:

    with st.chat_message(message["role"]):

        if message["type"] == "text":

            st.markdown(message["content"])

        elif message["type"] == "result":

            render_result(
                message["result"]
            )




# ---------------------------------------------------------------------
# CHAT INPUT
# ---------------------------------------------------------------------

chat_submission = st.chat_input(
    "Upload an invoice PDF or ask a question about the current invoice...",
    accept_file=True,
    file_type=["pdf"],
)


# ---------------------------------------------------------------------
# HANDLE SUBMISSION
# ---------------------------------------------------------------------

if chat_submission:

    uploaded_files = chat_submission.get(
        "files",
        [],
    )

    # -------------------------------------------------------------
    # No file
    # -------------------------------------------------------------

    if not uploaded_files:

        typed = chat_submission.get("text", "").strip()
        if not typed:
            st.stop()

        # Text after an invoice is uploaded = grounded natural-language chat.
        if st.session_state.invoice_context is not None:
            st.session_state.messages.append({
                "role": "user", "type": "text", "content": typed
            })
            st.session_state.chat_history.append({
                "role": "user", "content": typed
            })

            with st.chat_message("user"):
                st.markdown(typed)
            with st.chat_message("assistant"):
                with st.spinner("Thinking about the verified evidence..."):
                    try:
                        answer = ask_mistral_about_invoice(typed)
                    except Exception as exc:
                        st.error("Mistral could not answer this question.")
                        st.exception(exc)
                        st.stop()
                st.markdown(answer)

            # TWO stores, and both need the answer.
            #
            # chat_history is the LLM's context window. messages is what the
            # replay loop re-renders on every Streamlit rerun. The answer was
            # being written ONLY to chat_history, so it survived as context the
            # model could see and vanished from the screen the moment the next
            # question triggered a rerun -- the user asked a second question
            # and the first answer disappeared.
            st.session_state.chat_history.append({
                "role": "assistant", "content": answer
            })
            st.session_state.messages.append({
                "role": "assistant", "type": "text", "content": answer
            })

        else:
            # PO-id fallback, for driving the checks without a PDF.
            #
            # This branch used to hand checks 2 and 3 a hardcoded vendor,
            # amount and period so that they always had something to grade.
            # They duly graded an invoice nobody submitted: on CO80ROOF2 it
            # named the wrong vendor and reported "no duplicate" against a
            # PO carrying an exact one -- and both counted as applicable
            # PASSES, padding the score to 3/4. That is the fabricated
            # receipt this project exists to catch, built by this project.
            #
            # Read the real row instead; when there is no real row, run only
            # the check that has an input.
            candidate = typed.upper()
            ledger = invoices_by_po.get(candidate, [])

            result = None

            if ledger:
                # Several invoices on one PO IS the duplicate case. The one
                # awaiting a decision is the latest to arrive.
                ledger_invoice = max(
                    ledger,
                    key=lambda inv: inv.submitted_at,
                )
                result = run_invoice_checks(
                    {
                        "invoice_id": ledger_invoice.invoice_id,
                        "po_id": ledger_invoice.po_id,
                        "vendor_name": ledger_invoice.vendor_name,
                        "amount": ledger_invoice.amount,
                        "period": ledger_invoice.period,
                        "date": ledger_invoice.submitted_at,
                        "raw_text": (
                            "(typed po_id — read from data/invoices.csv, "
                            "so there is no OCR text)"
                        ),
                    },
                    invoice=ledger_invoice,
                )
            elif candidate in erp_by_fms:
                result = run_po_lookup(candidate)

            if result is not None:
                st.session_state.invoice_context = build_invoice_llm_context(result)
                st.session_state.chat_history = []
                st.session_state.messages.append({
                    "role": "user", "type": "text", "content": f"PO `{candidate}`"
                })
                st.session_state.messages.append({
                    "role": "assistant", "type": "result", "result": result
                })
                with st.chat_message("assistant"):
                    render_result(result)
            else:
                st.session_state.messages.append({
                    "role": "user", "type": "text", "content": typed
                })
                with st.chat_message("assistant"):
                    st.write(
                        "Upload an invoice PDF first, or type a po_id. "
                        "Once an invoice is verified, you can ask natural-language questions about it."
                    )
                    st.caption(
                        "534 POs carry an invoice in data/invoices.csv. "
                        "Those run all four checks:"
                    )
                    st.code(
                        "P-3RV105L   APPROVE   4/4 — vendor resolves, no duplicate, job live\n"
                        "BED-807     COMMENT   duplicate found, but the job is still live\n"
                        "CO80ROOF2   DENY      duplicate of INV-00055, and the job is (Completed)",
                        language="text",
                    )
                    st.caption(
                        "The other 5,074 POs carry no invoice, so checks 1–3 have no "
                        "input and do not run. Below is what check 4 alone returns — "
                        "the overall decision is COMMENT unless the job is dead:"
                    )
                    st.code(
                        "CA202HS04   check 4 APPROVE   live phase, agency record on file\n"
                        "BX024-011   check 4 DENY      the job is (Completed)\n"
                        "HWK973      check 4 DENY      one dead record among live ones\n"
                        "52CHAMELV   check 4 COMMENT   (Inactive) -- on hold\n"
                        "ACSPDF      check 4 COMMENT   (Pending) -- NYC defines it nowhere\n"
                        "ACECUN211   check 4 COMMENT   no agency record to verify against",
                        language="text",
                    )

    # -------------------------------------------------------------
    # PDF uploaded
    # -------------------------------------------------------------

    else:

        uploaded_file = uploaded_files[0]

        # A new PDF starts a new invoice conversation.
        st.session_state.chat_history = []
        st.session_state.invoice_context = None

        # User message
        st.session_state.messages.append(
            {
                "role": "user",
                "type": "text",
                "content": (
                    f"📎 Uploaded `{uploaded_file.name}`"
                ),
            }
        )

        with st.chat_message("user"):

            st.write(
                f"📎 `{uploaded_file.name}`"
            )

        # Assistant
        with st.chat_message("assistant"):

            with st.status(
                "Verifying invoice...",
                expanded=True,
            ) as status:

                # -------------------------------------------------
                # Mistral OCR + extraction
                # -------------------------------------------------

                st.write(
                    "🤖 Reading invoice with Mistral OCR..."
                )

                try:

                    extracted, raw_text = run_mistral_ocr(
                        uploaded_file
                    )

                except Exception as exc:

                    status.update(
                        label="Mistral OCR failed",
                        state="error",
                    )

                    st.error(
                        "Mistral OCR could not process this invoice."
                    )

                    st.exception(exc)

                    st.stop()

                fields = normalize_invoice_fields(
                    extracted,
                    raw_text,
                )

                st.write(
                    "✓ Invoice fields extracted"
                )

                # -------------------------------------------------
                # Validate
                # -------------------------------------------------

                errors = validate_invoice(
                    fields
                )

                if errors:

                    status.update(
                        label="Invoice extraction incomplete",
                        state="error",
                    )

                    st.error(
                        "I couldn't extract the fields required "
                        "by the verification checks."
                    )

                    for error in errors:

                        st.write(
                            f"- {error}"
                        )

                    with st.expander(
                        "View Mistral extracted data"
                    ):

                        st.json(
                            extracted
                        )

                    with st.expander(
                        "View Mistral OCR text"
                    ):

                        st.text(
                            raw_text
                        )

                    st.stop()

                # -------------------------------------------------
                # Deterministic verification
                # -------------------------------------------------

                st.write("🔎 Running deterministic verification checks...")

                try:
                    result = run_invoice_checks(fields)
                except Exception as exc:
                    status.update(label="Verification failed", state="error")
                    st.exception(exc)
                    st.stop()

                # Check 1 gates everything else.
                if result["intake"].outcome != "APPROVE":
                    st.write("⚠ Intake check failed — downstream checks were not run.")
                else:
                    st.write("✓ Intake check passed")
                    st.write(
                        "✓ Vendor entity verified"
                        if result["vendor"]["passed"]
                        else "⚠ Vendor entity requires review"
                    )
                    st.write(
                        "✓ No duplicate payment found"
                        if result["duplicate"]["passed"]
                        else "⚠ Payment duplication issue detected"
                    )
                    if result["job_status"]["outcome"] == "APPROVE":
                        st.write("✓ Job status verified")
                    elif result["job_status"]["outcome"] == "DENY":
                        st.write("✕ Job is not accepting charges")
                    else:
                        st.write("⚠ Job status could not be established")

                # -------------------------------------------------
                # Finish
                # -------------------------------------------------

                status.update(
                    label="Verification complete",
                    state="complete",
                )

            # Render final result
            render_result(
                result
            )

        # Save the read-only evidence package used by the chat layer.
        st.session_state.invoice_context = build_invoice_llm_context(result)

        # Store result in history
        st.session_state.messages.append(
            {
                "role": "assistant",
                "type": "result",
                "result": result,
            }
        )