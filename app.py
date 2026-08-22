from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path
from typing import Any

import streamlit as st
from mistralai.client import Mistral

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
    page_title="Invoice Verification",
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

st.title("🧾 Invoice Verification")

st.caption(
    "Upload an incoming invoice. "
    "Mistral OCR extracts the invoice data, then vendor entity "
    "and payment duplication checks run automatically."
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
        "MISTRAL_API_KEY is not set, so PDF upload is disabled. "
        "Type a po_id instead — the vendor, duplicate and job-status checks "
        "run against the committed CSVs and need no key."
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

    return (
        resolver,
        invoices,
        valid_fms_ids,
        erp_by_fms,
    )


try:

    (
        resolver,
        existing_invoices,
        valid_fms_ids,
        erp_by_fms,
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
        include_blocks=True,
        confidence_scores_granularity="page",
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

    # Compare against historical invoices
    combined = (
        existing_invoices
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
):

    # ---- CHECK 1 GATES EVERYTHING ---------------------------------------
    # If the document cannot be trusted as an invoice, the later checks are
    # NOT RUN -- not "passed". Running them on garbage fields produces three
    # confident answers about a document nobody read, which is exactly the
    # fabricated receipt this project is named after.
    intake = run_intake_check(fields)

    if intake.outcome != "APPROVE":

        return {
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


# ---------------------------------------------------------------------
# RENDER RESULT
# ---------------------------------------------------------------------

def render_result(
    result: dict,
):

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
            f"**{len(existing_invoices):,}** historical invoices."
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

    # ---- check 4 evidence, before the verdict ------------------------
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
    "Upload an invoice PDF...",
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
        typed = chat_submission.get(
            "text",
            "",
        ).strip()

        st.session_state.messages.append(
            {
                "role": "user",
                "type": "text",
                "content": typed,
            }
        )

        # ---------------------------------------------------------
        # TYPED po_id FALLBACK.
        # The repo ships ZERO invoice PDFs -- data/invoices.csv points at
        # docs/invoices/*.pdf that were never committed -- so without this a
        # fresh clone cannot exercise the app at all. Typing a po_id runs the
        # same three checks against the real ERP rows, skipping only the PDF
        # extraction step.
        # ---------------------------------------------------------
        candidate = typed.upper()

        if candidate in erp_by_fms:

            result = run_invoice_checks(
                {
                    "invoice_id": f"TYPED-{candidate}",
                    "po_id": candidate,
                    "vendor_name": "Brooklyn Public Library",
                    "amount": 50000.00,
                    "period": "202605",
                    "date": "2026-05-15",
                    "raw_text": (
                        "(typed po_id — no PDF, so no OCR text)"
                    ),
                }
            )

            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "type": "result",
                    "result": result,
                }
            )

            with st.chat_message("assistant"):
                render_result(result)

        else:

            with st.chat_message("assistant"):

                st.write(
                    "Attach an invoice PDF, or type a po_id. These six are "
                    "one per outcome:"
                )
                st.code(
                    "CA202HS04   APPROVE   live phase, agency record on file\n"
                    "BX024-011   DENY      the job is (Completed)\n"
                    "HWK973      DENY      one dead record among live ones\n"
                    "52CHAMELV   COMMENT   (Inactive) -- on hold\n"
                    "ACSPDF      COMMENT   (Pending) -- NYC defines it nowhere\n"
                    "ACECUN211   COMMENT   no agency record to verify against",
                    language="text",
                )

    # -------------------------------------------------------------
    # PDF uploaded
    # -------------------------------------------------------------

    else:

        uploaded_file = uploaded_files[0]

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
                # Vendor check
                # -------------------------------------------------

                st.write(
                    "🏢 Running vendor entity check..."
                )

                try:

                    result = run_invoice_checks(
                        fields
                    )

                except Exception as exc:

                    status.update(
                        label="Verification failed",
                        state="error",
                    )

                    st.exception(exc)

                    st.stop()

                if result["vendor"]["passed"]:

                    st.write(
                        "✓ Vendor entity verified"
                    )

                else:

                    st.write(
                        "⚠ Vendor entity requires review"
                    )

                # -------------------------------------------------
                # Duplicate check
                # -------------------------------------------------

                st.write(
                    "💳 Running payment duplication check..."
                )

                if result["duplicate"]["passed"]:

                    st.write(
                        "✓ No duplicate payment found"
                    )

                else:

                    st.write(
                        "⚠ Payment duplication issue detected"
                    )

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

        # Store result in history
        st.session_state.messages.append(
            {
                "role": "assistant",
                "type": "result",
                "result": result,
            }
        )