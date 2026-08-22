"""
Streamlit demo: paste one or more candidate invoices as JSON and see
check 2 (vendor entity resolution) and check 3 (duplicate payment check)
run against them, using the real committed data/ as the reference corpus.

Run from repo root:
    streamlit run demo/app.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "checks"))

from checks.common import Invoice, load_erp, load_invoices, load_vendors  # noqa: E402
from checks.duplicate_payment import find_duplicates, find_orphan_pos  # noqa: E402
from checks.vendor_resolution import VendorResolver  # noqa: E402

REQUIRED_FIELDS = ["invoice_id", "po_id", "vendor_name", "amount", "period", "status", "submitted_at"]

SAMPLES: dict[str, list[dict]] = {
    "Sample 1 -- pass (clean, exact vendor match)": [{
        "invoice_id": "INV-90001", "po_id": "HWPR23KR",
        "vendor_name": "Brooklyn Public Library",
        "amount": 45210.00, "period": "202606",
        "status": "pending", "submitted_at": "2026-06-01",
    }],
    "Sample 2 -- pass (alias resolved, fuzzy match)": [{
        "invoice_id": "INV-90002", "po_id": "SANDSHORE",
        "vendor_name": "Brooklyn Public Libary",
        "amount": 12800.50, "period": "202606",
        "status": "pending", "submitted_at": "2026-06-02",
    }],
    "Sample 3 -- fail (unresolved vendor + orphan po_id)": [{
        "invoice_id": "INV-90003", "po_id": "PO-DOES-NOT-EXIST",
        "vendor_name": "Zzyzx Consolidated Holdings Group",
        "amount": 500000.00, "period": "202606",
        "status": "pending", "submitted_at": "2026-06-03",
    }],
    "Sample 4 -- fail (duplicate of an existing paid invoice)": [{
        "invoice_id": "INV-90004", "po_id": "P-3RV105L",
        "vendor_name": "Brighter Choice Community School",
        "amount": 33256.99, "period": "202605",
        "status": "pending", "submitted_at": "2026-05-30",
    }],
}


@st.cache_resource
def load_reference():
    vendors = load_vendors()
    erp = load_erp()
    existing_invoices = load_invoices()
    resolver = VendorResolver(vendors)
    valid_fms_ids = {row.fms_id for row in erp}
    return resolver, existing_invoices, valid_fms_ids


def to_invoice(raw: dict) -> Invoice:
    return Invoice(
        invoice_id=raw["invoice_id"],
        po_id=raw["po_id"],
        vendor_id="",  # never supplied -- check 2 is what predicts this
        vendor_name=raw["vendor_name"],
        amount=float(raw["amount"]),
        period=str(raw["period"]),
        status=raw["status"],
        submitted_at=raw["submitted_at"],
        doc_uri=raw.get("doc_uri", ""),
        missing_field=raw.get("missing_field", "none"),
        label_is_duplicate=False,
        label_dead_job=False,
    )


def validate(rows: list[dict]) -> list[str]:
    errors = []
    for i, row in enumerate(rows):
        missing = [f for f in REQUIRED_FIELDS if f not in row]
        if missing:
            errors.append(f"row {i}: missing field(s) {missing}")
            continue
        try:
            float(row["amount"])
        except (TypeError, ValueError):
            errors.append(f"row {i}: amount {row['amount']!r} is not a number")
    return errors


st.set_page_config(page_title="Check 2 / Check 3 demo", layout="wide")
st.title("Vendor resolution + duplicate payment check")
st.caption(
    "Paste candidate invoices as JSON. Check 2 resolves vendor_name to a "
    "canonical vendor_id (no vendor_id in the input -- that's the answer "
    "column). Check 3 validates po_id against erp.fms_id and looks for "
    "duplicate payments against the committed invoices.csv plus anything "
    "else in this same batch."
)

resolver, existing_invoices, valid_fms_ids = load_reference()

with st.sidebar:
    st.subheader("Reference data loaded")
    st.write(f"vendors: {len(resolver.vendors)}")
    st.write(f"known fms_id: {len(valid_fms_ids)}")
    st.write(f"existing invoices: {len(existing_invoices)}")
    if resolver.collisions:
        st.warning(
            f"{len(resolver.collisions)} normalized vendor name(s) map to "
            f"more than one vendor_id in vendors.csv -- see console/expander below."
        )

sample_choice = st.selectbox("Load a sample", ["Custom JSON"] + list(SAMPLES.keys()))
default_json = json.dumps(
    SAMPLES.get(sample_choice, SAMPLES["Sample 1 -- pass (clean, exact vendor match)"]),
    indent=2,
)
raw_text = st.text_area("Invoice JSON (a list of objects)", value=default_json, height=260)

run = st.button("Run checks", type="primary")

if run:
    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            parsed = [parsed]
    except json.JSONDecodeError as e:
        st.error(f"Invalid JSON: {e}")
        st.stop()

    errors = validate(parsed)
    if errors:
        st.error("Fix these before running checks:\n" + "\n".join(f"- {e}" for e in errors))
        st.stop()

    new_invoices = [to_invoice(r) for r in parsed]

    orphans = set(find_orphan_pos(new_invoices, valid_fms_ids))
    combined = existing_invoices + new_invoices
    findings = find_duplicates(combined, resolver)
    findings_by_invoice = {f.invoice_id: f for f in findings}

    st.subheader("Results")
    for inv in new_invoices:
        res = resolver.resolve(inv.vendor_name)
        dup = findings_by_invoice.get(inv.invoice_id)
        is_orphan = inv.invoice_id in orphans

        check2_pass = res.status == "merged"
        check3_pass = not is_orphan and dup is None

        col1, col2 = st.columns(2)
        with col1:
            st.markdown(f"#### {inv.invoice_id}")
            st.write(f"vendor_name: `{inv.vendor_name}`")
            st.write(f"po_id: `{inv.po_id}`  ·  amount: `{inv.amount}`  ·  period: `{inv.period}`")

        with col2:
            if check2_pass:
                st.success(
                    f"check 2 PASS -- resolved to {res.vendor_id} "
                    f"({res.canonical_name}), method={res.method}, score={res.score:.3f}"
                )
            else:
                st.error(
                    f"check 2 FAIL -- sent to review "
                    f"(best candidate score={res.score:.3f}, method={res.method})"
                )

            if check3_pass:
                st.success("check 3 PASS -- valid po_id, no duplicate found")
            elif is_orphan:
                st.error("check 3 FAIL -- po_id does not match any known fms_id (orphan PO)")
            else:
                st.error(
                    f"check 3 FAIL -- {dup.kind} duplicate of {dup.matched_invoice_id} "
                    f"(action: {dup.action})"
                )
        st.divider()

    if resolver.collisions:
        with st.expander("Vendor master ambiguities (not caused by your input)"):
            for key, vids in resolver.collisions.items():
                st.write(f"`{key}` -> {sorted(vids)}")
