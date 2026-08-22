"""
Invoice Verification Chat Demo

Flow:
    PDF invoice
        |
        v
    Extract invoice fields
        |
        +--> Vendor Entity Check
        |
        +--> Payment Duplication Check
        |
        v
    FINAL DECISION
        CLEAR / HOLD

Run:
    streamlit run app.py

Install:
    pip install streamlit pypdf
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import streamlit as st


# ---------------------------------------------------------------------
# PATHS
# ---------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent

# Allow imports from checks/
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

    .decision-block {
        background: rgba(220, 53, 69, .10);
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

    .check-title {
        font-size: 18px;
        font-weight: 700;
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
    "Vendor entity and payment duplication checks run automatically."
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
# PDF TEXT EXTRACTION
# ---------------------------------------------------------------------

def extract_pdf_text(uploaded_file) -> str:
    """
    Extract text from a normal text-based PDF.

    For scanned/image-only invoices, OCR would be needed.
    """

    try:

        from pypdf import PdfReader

    except ImportError:

        st.error(
            "pypdf is not installed. Run: pip install pypdf"
        )

        st.stop()

    uploaded_file.seek(0)

    reader = PdfReader(uploaded_file)

    pages = []

    for page in reader.pages:

        text = page.extract_text() or ""

        pages.append(text)

    return "\n".join(pages)


# ---------------------------------------------------------------------
# TEXT HELPERS
# ---------------------------------------------------------------------

def clean_text(value: str) -> str:

    value = value.replace("\xa0", " ")

    value = re.sub(
        r"[ \t]+",
        " ",
        value,
    )

    value = re.sub(
        r"\n{3,}",
        "\n\n",
        value,
    )

    return value.strip()


def find_first(
    text: str,
    patterns: list[str],
) -> str | None:

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )

        if match:

            return match.group(1).strip()

    return None


def parse_amount(value: str | None) -> float | None:

    if not value:
        return None

    cleaned = (
        value
        .replace("$", "")
        .replace(",", "")
        .replace("USD", "")
        .strip()
    )

    try:

        return float(cleaned)

    except ValueError:

        return None


# ---------------------------------------------------------------------
# INVOICE EXTRACTION
# ---------------------------------------------------------------------

def extract_invoice_fields(
    text: str,
) -> dict[str, Any]:

    text = clean_text(text)

    invoice_id = find_first(
        text,
        [
            r"(?:invoice\s*(?:number|no\.?|#)|inv(?:oice)?\s*#?)\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-_\/]+)",
        ],
    )

    vendor_name = find_first(
        text,
        [
            r"(?:vendor|supplier|seller)\s*(?:name)?\s*[:\-]\s*(.+)",
            r"(?:from)\s*[:\-]\s*(.+)",
        ],
    )

    po_id = find_first(
        text,
        [
            r"(?:purchase\s*order|po)\s*(?:number|no\.?|#|id)?\s*[:\-]?\s*([A-Z0-9][A-Z0-9\-_\/]+)",
        ],
    )

    amount_raw = find_first(
        text,
        [
            r"(?:total\s*due|invoice\s*total|grand\s*total|amount\s*due|total)\s*[:\-]?\s*\$?\s*([\d,]+\.\d{2})",
        ],
    )

    date = find_first(
        text,
        [
            r"(?:invoice\s*date|date)\s*[:\-]\s*([0-9]{1,4}[\/\-][0-9]{1,2}[\/\-][0-9]{1,4})",
        ],
    )

    amount = parse_amount(amount_raw)

    # -------------------------------------------------------------
    # Period
    # -------------------------------------------------------------
    period = ""

    if date:

        digits = re.findall(
            r"\d+",
            date,
        )

        if len(digits) >= 3:

            # Best-effort YYYYMM
            year = None
            month = None

            for d in digits:

                if len(d) == 4:
                    year = d

            if year:

                for d in digits:

                    if len(d) <= 2:

                        n = int(d)

                        if 1 <= n <= 12:

                            month = f"{n:02d}"
                            break

                if month:

                    period = f"{year}{month}"

    # Fallback to current demo period
    if not period:

        from datetime import datetime

        period = datetime.now().strftime("%Y%m")

    return {
        "invoice_id": invoice_id,
        "vendor_name": vendor_name,
        "po_id": po_id,
        "amount": amount,
        "date": date,
        "period": period,
        "raw_text": text,
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
            "Could not extract invoice number."
        )

    if not fields.get("vendor_name"):
        errors.append(
            "Could not extract vendor name."
        )

    if not fields.get("po_id"):
        errors.append(
            "Could not extract PO number."
        )

    if fields.get("amount") is None:
        errors.append(
            "Could not extract invoice amount."
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
        "View extracted invoice data"
    ):

        st.json(
            {
                key: value
                for key, value in fields.items()
                if key != "raw_text"
            }
        )

    with st.expander(
        "View extracted PDF text"
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
                # Extraction
                # -------------------------------------------------

                st.write(
                    "📄 Extracting invoice fields..."
                )

                try:

                    pdf_text = extract_pdf_text(
                        uploaded_file
                    )

                except Exception as exc:

                    status.update(
                        label="PDF extraction failed",
                        state="error",
                    )

                    st.error(
                        str(exc)
                    )

                    st.stop()

                if not pdf_text.strip():

                    status.update(
                        label="No text found in PDF",
                        state="error",
                    )

                    st.error(
                        "This appears to be a scanned/image-only PDF. "
                        "OCR is required for this invoice."
                    )

                    st.stop()

                fields = extract_invoice_fields(
                    pdf_text
                )

                # -------------------------------------------------
                # Validate
                # -------------------------------------------------

                errors = validate_invoice(
                    fields
                )

                if errors:

                    status.update(
                        label="Could not extract required fields",
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
                        "View extracted PDF text"
                    ):

                        st.text(
                            pdf_text
                        )

                    st.stop()

                st.write(
                    "✓ Invoice fields extracted"
                )

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