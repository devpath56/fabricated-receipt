-- Schema for the invoice-validation module.
-- Tables 1 and 2 are loaded from the NYC Capital Projects Dashboard CSVs
-- (etl/upsert.py). Table 3 and the vendor tables are synthetic, built for
-- this demo (etl/seed_table3.py).

PRAGMA foreign_keys = ON;

-- ── Table 1: Citywide Budget and Schedule ───────────────────────────────
-- One row per (fms_id, reporting_period) snapshot. current_phase is the
-- field the Job Status check reads.
CREATE TABLE IF NOT EXISTS budget_and_schedule (
    reporting_period            TEXT NOT NULL,
    managing_agency             TEXT,
    sponsor_agency               TEXT,
    pid                          TEXT,
    fms_id                       TEXT NOT NULL,
    total_budget                 REAL,
    spend_to_date                 REAL,
    spend_to_date_pct             REAL,
    fms_project_name             TEXT,
    agency_project_name          TEXT,
    agency_project_description   TEXT,
    current_phase                TEXT,
    borough                       TEXT,
    community_board               TEXT,
    budget_line                   TEXT,
    ten_year_plan_category        TEXT,
    fms_data_date                 TEXT,
    PRIMARY KEY (fms_id, reporting_period)
);

CREATE INDEX IF NOT EXISTS idx_bas_fms_id ON budget_and_schedule(fms_id);

-- ── Table 2: Budget Spend History and Variance ──────────────────────────
-- One row per (fms_id, year_month_reported) snapshot.
CREATE TABLE IF NOT EXISTS spend_history (
    managing_agency       TEXT,
    fms_id                 TEXT NOT NULL,
    year_month_reported    TEXT NOT NULL,
    total_budget            REAL,
    spend_to_date            REAL,
    spend_to_date_pct        REAL,
    budget_variance          REAL,
    budget_variance_pct      REAL,
    PRIMARY KEY (fms_id, year_month_reported)
);

CREATE INDEX IF NOT EXISTS idx_sh_fms_id ON spend_history(fms_id);

-- ── Vendor bridge tables (synthetic) ────────────────────────────────────
-- Canonical vendor identities. vendor_name here is the "correct" spelling.
CREATE TABLE IF NOT EXISTS vendor_master (
    vendor_id     TEXT PRIMARY KEY,
    vendor_name   TEXT NOT NULL
);

-- Which vendor is actually contracted against which fms_id. This is the
-- source of truth the Vendor Resolution check validates invoices against.
CREATE TABLE IF NOT EXISTS fms_vendor (
    fms_id       TEXT PRIMARY KEY,
    vendor_id     TEXT NOT NULL REFERENCES vendor_master(vendor_id)
);

-- ── Table 3: Invoices (synthetic) ───────────────────────────────────────
-- vendor_id is the CLAIMED vendor on the invoice (may be wrong or absent
-- from fms_vendor). vendor_name is the raw, possibly-inconsistent string
-- as it appeared on the submitted invoice -- this is deliberately kept
-- alongside vendor_id so resolution has real drift to catch.
CREATE TABLE IF NOT EXISTS invoices (
    invoice_id        TEXT PRIMARY KEY,
    fms_id             TEXT NOT NULL,
    vendor_id          TEXT NOT NULL,
    vendor_name        TEXT NOT NULL,
    invoice_number     TEXT NOT NULL,
    billing_period     TEXT NOT NULL,      -- 'YYYY-MM'
    amount             REAL NOT NULL,
    payment_status     TEXT NOT NULL CHECK (payment_status IN
                         ('SUBMITTED','APPROVED','PAID','DENIED'))
);

CREATE INDEX IF NOT EXISTS idx_inv_fms          ON invoices(fms_id);
CREATE INDEX IF NOT EXISTS idx_inv_dup_fingerprint
    ON invoices(fms_id, billing_period, amount, vendor_id);
CREATE INDEX IF NOT EXISTS idx_inv_invoice_number ON invoices(invoice_number);
