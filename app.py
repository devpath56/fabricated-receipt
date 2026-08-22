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

if not MISTRAL_API_KEY:
    st.error(
        "MISTRAL_API_KEY is not set. "
        "Set it in your environment before starting the app."
    )
    st.code(
        '$env:MISTRAL_API_KEY="your_mistral_api_key_here"',
        language="powershell",
    )
    st.stop()

mistral_client = Mistral(api_key=MISTRAL_API_KEY)


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

    return (
        resolver,
        invoices,
        valid_fms_ids,
    )


try:

    (
        resolver,
        existing_invoices,
        valid_fms_ids,
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
# CHAT HISTORY
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
# DECISION
# ---------------------------------------------------------------------

def make_decision(
    vendor_result: dict,
    duplicate_result: dict,
) -> str:

    if (
        vendor_result["passed"]
        and duplicate_result["passed"]
    ):

        return "CLEAR"

    return "HOLD"


# ---------------------------------------------------------------------
# RESULT OBJECT
# ---------------------------------------------------------------------

def run_invoice_checks(
    fields: dict[str, Any],
):

    invoice = make_invoice(
        fields
    )

    vendor_result = run_vendor_check(
        invoice
    )

    duplicate_result = run_duplicate_check(
        invoice
    )

    decision = make_decision(
        vendor_result,
        duplicate_result,
    )

    return {
        "invoice": invoice,
        "fields": fields,
        "vendor": vendor_result,
        "duplicate": duplicate_result,
        "decision": decision,
    }


# ---------------------------------------------------------------------
# RENDER RESULT
# ---------------------------------------------------------------------

def render_result(
    result: dict,
):

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

    if decision == "CLEAR":

        st.markdown(
            """
            <div class="decision decision-clear">
                <div class="decision-title">✓ CLEAR</div>
                <div class="decision-subtitle">
                    Vendor verified and no duplicate payment detected.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    else:

        st.markdown(
            """
            <div class="decision decision-hold">
                <div class="decision-title">⚠ HOLD</div>
                <div class="decision-subtitle">
                    Invoice requires manual review before payment.
                </div>
            </div>
            """,
            unsafe_allow_html=True,
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
            fields["raw_text"]
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

        st.session_state.messages.append(
            {
                "role": "user",
                "type": "text",
                "content": chat_submission.get(
                    "text",
                    "",
                ),
            }
        )

        with st.chat_message("assistant"):

            st.write(
                "Please attach an invoice PDF so I can run the "
                "vendor entity and payment duplication checks."
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