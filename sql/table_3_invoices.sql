-- ============================================================================
-- table_3_invoices  —  minimal invoice tracking for three validation checks
--
-- GROUNDED IN, not modelled on:
--   Table 1  data.cityofnewyork.us/City-Government/.../fb86-vt7u   56,525 rows
--   Table 2  data.cityofnewyork.us/d/qj5n-h5qp                     53,495 rows
--   Both downloaded and profiled 2026-08-22. Every claim below is from those files.
--
-- THE ONE FACT THAT SHAPES THIS SCHEMA:
--   `FMS ID` IS NOT AN INTEGER AND IS NOT UNIQUE IN TABLE 1.
--   Format, measured over 56,525 T1 rows (8,171 distinct ids), lengths 5-9:
--       MC024-008  E23-0010  CA054BX18  BXELEVFAR  ACSPDF  JJCONS  61608113
--   Table 1 is a TIME SERIES: 10 reporting periods, 202305 .. 202605. Its grain is
--   (Reporting Period, FMS ID) -- and even that is not unique: 54,865 distinct pairs
--   over 56,525 rows. Inside the newest period alone, 5,801 rows carry 5,608 distinct
--   FMS IDs. 97 FMS IDs map to more than one PID; 39 carry more than one Managing Agency.
--
--   THEREFORE A DIRECT FOREIGN KEY TO TABLE 1 CANNOT BE DECLARED. There is no column
--   set in Table 1 that is both unique and equal to `fms_id`. The reference below is to
--   a materialised current-projects view; declaring `REFERENCES table_1(fms_id)` against
--   the raw file would fail at DDL time, and inventing a surrogate key would break the
--   grounding requirement. This is stated rather than worked around.
-- ============================================================================

-- The join target. One row per fms_id, taken from the newest reporting period.
-- It exists so `fms_id` has something unique to point at; it invents no key.
CREATE TABLE table_1_current_projects (
    fms_id            VARCHAR(16)  PRIMARY KEY,
    current_phase     VARCHAR(64)  NOT NULL,
    managing_agency   VARCHAR(16)  NOT NULL,
    total_budget      NUMERIC(15,2),
    spend_to_date     NUMERIC(15,2),
    reporting_period  CHAR(6)      NOT NULL   -- 'YYYYMM', Table 1's own format
);

CREATE TABLE table_3_invoices (
    invoice_id      VARCHAR(32)   PRIMARY KEY,
    fms_id          VARCHAR(16)   NOT NULL
                    REFERENCES table_1_current_projects (fms_id),
    vendor_id       VARCHAR(32)   NOT NULL,
    vendor_name     VARCHAR(255)  NOT NULL,
    invoice_number  VARCHAR(64)   NOT NULL,
    billing_period  CHAR(7)       NOT NULL
                    CHECK (billing_period ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    amount          NUMERIC(15,2) NOT NULL CHECK (amount > 0),
    payment_status  VARCHAR(9)    NOT NULL
                    CHECK (payment_status IN ('SUBMITTED','APPROVED','PAID','DENIED')),

    -- CHECK 3, PART A — the strong duplicate signal. A contractor's own invoice number
    -- is unique within that contractor, never across contractors, so the constraint is
    -- (vendor_id, invoice_number) and never invoice_number alone.
    CONSTRAINT uq_vendor_invoice_number UNIQUE (vendor_id, invoice_number),

    -- CHECK 3, PART B — the "or an equivalent one" clause. Catches a resubmission under
    -- a new invoice_number: same vendor, same project, same month, same amount.
    CONSTRAINT uq_equivalent_invoice UNIQUE (fms_id, vendor_id, billing_period, amount)
);

-- CHECK 1 — Job Status. Table 1's convention, verified across all 61 distinct
-- Current Phase values: a phase in PARENTHESES is not an active work phase
-- ((Pending) 12,145 · (Completed) 4,854 · (Cancelled) 788 · (On-Hold) 464 ...),
-- a bare phase is (Construction 7,837 · Design 6,625 · Close-out 4,420 ...).
-- CASING IS NOT CLEAN IN THE SOURCE and the index must absorb it:
--   (Cancelled) 788 / (cancelled) 28 / (CANCELLED) 1
--   (On-Hold) 464 / (On-hold) 304 / (On Hold) 1
--   Construction 7,837 / CONSTRUCTION 1 ; Construction Procurement 3,762 / Construction procurement 52
CREATE INDEX ix_t1_phase_active ON table_1_current_projects (
    (current_phase NOT LIKE '(%'), lower(current_phase)
);

-- CHECK 2 — Vendor Resolution. The comparison is vendor_name against the canonical
-- name for vendor_id. NEITHER SOURCE TABLE CARRIES A VENDOR COLUMN — a scan of all 27
-- Table 1 columns and all 8 Table 2 columns returns none — so this pair is the demo's
-- declared simplification and is grounded in the prompt, not in the data.
CREATE INDEX ix_invoice_vendor ON table_3_invoices (vendor_id, vendor_name);

-- Supporting index for the amount-plausibility read against Table 1 / Table 2.
CREATE INDEX ix_invoice_fms_period ON table_3_invoices (fms_id, billing_period);
