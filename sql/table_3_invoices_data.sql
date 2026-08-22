-- ============================================================================
-- 15 synthetic invoices for table_3_invoices
--
-- GROUNDING: every fms_id, current_phase and total_budget below was read from
-- Table 1 (fb86-vt7u), Reporting Period 202605 — the newest of its 10 periods.
-- Every billing_period corresponds to a Year-Month Reported that actually exists
-- for that fms_id in Table 2 (qj5n-h5qp): 202505, 202509, 202601.
-- Nothing here is invented except the vendor columns, which no source table has.
--
-- READ THIS BEFORE RUNNING: THE SCHEMA REJECTS THE DUPLICATES ON PURPOSE.
-- table_3_invoices declares UNIQUE (vendor_id, invoice_number) and
-- UNIQUE (fms_id, vendor_id, billing_period, amount). INV-1006 violates the first,
-- INV-1006 and INV-1008 violate the second — which is the constraints working.
-- But a demo of a DUPLICATE-PAYMENT CHECK needs the bad rows to land so the check
-- has something to find; with the constraints on, the database answers the question
-- first and the check is unreachable. Choose one, deliberately:
--   (a) demo the CHECK  -> run the two ALTERs below, load all 15, let the check fire
--   (b) demo the SCHEMA -> load 13, and INV-1006/INV-1008 fail at INSERT with 23505
-- (a) is what the answer key at the bottom assumes.
-- ============================================================================

-- (a) only: demote the two guards to non-unique indexes so the rows can land.
ALTER TABLE table_3_invoices DROP CONSTRAINT uq_vendor_invoice_number;
ALTER TABLE table_3_invoices DROP CONSTRAINT uq_equivalent_invoice;
CREATE INDEX ix_vendor_invoice_number ON table_3_invoices (vendor_id, invoice_number);
CREATE INDEX ix_equivalent_invoice   ON table_3_invoices (fms_id, vendor_id, billing_period, amount);


-- MC024-008: Table 1 current_phase = Design, total_budget = $1,592,955.31, spend_to_date = $71,955.31
-- INV-1001: 18% of $1,592,955 = $286,731.96
INSERT INTO table_3_invoices (invoice_id, fms_id, vendor_id, vendor_name, invoice_number, billing_period, amount, payment_status)
VALUES ('INV-1001', 'MC024-008', 'V001', 'Skyline Structural Group LLC', 'SKY-2025-0417', '2025-05', 286731.96, 'PAID');
-- INV-1002: 12% of $1,592,955 = $191,154.64
INSERT INTO table_3_invoices (invoice_id, fms_id, vendor_id, vendor_name, invoice_number, billing_period, amount, payment_status)
VALUES ('INV-1002', 'MC024-008', 'V001', 'Skyline Structural Grp.', 'SKY-2025-0488', '2025-09', 191154.64, 'APPROVED');

-- YC002-023: Table 1 current_phase = Design, total_budget = $1,500,000.00, spend_to_date = $0.00
-- INV-1003: 22% of $1,500,000 = $330,000.00
INSERT INTO table_3_invoices (invoice_id, fms_id, vendor_id, vendor_name, invoice_number, billing_period, amount, payment_status)
VALUES ('INV-1003', 'YC002-023', 'V003', 'Empire Electrical Systems Corp.', 'EES-4471', '2025-09', 330000.00, 'SUBMITTED');

-- BX031-009: Table 1 current_phase = Construction, total_budget = $2,380,779.36, spend_to_date = $2,380,779.36
-- INV-1004: 30% of $2,380,779 = $714,233.81
INSERT INTO table_3_invoices (invoice_id, fms_id, vendor_id, vendor_name, invoice_number, billing_period, amount, payment_status)
VALUES ('INV-1004', 'BX031-009', 'V002', 'Hudson Mechanical Contractors Inc.', 'HMC-25-0912', '2025-09', 714233.81, 'PAID');

-- CA054BX18: Table 1 current_phase = Construction, total_budget = $6,973,000.00, spend_to_date = $4,229,239.94
-- INV-1005: 25% of $6,973,000 = $1,743,250.00
INSERT INTO table_3_invoices (invoice_id, fms_id, vendor_id, vendor_name, invoice_number, billing_period, amount, payment_status)
VALUES ('INV-1005', 'CA054BX18', 'V004', 'Northgate Civil Builders LLC', 'NCB-1180', '2025-05', 1743250.00, 'PAID');
-- INV-1006: 25% of $6,973,000 = $1,743,250.00
INSERT INTO table_3_invoices (invoice_id, fms_id, vendor_id, vendor_name, invoice_number, billing_period, amount, payment_status)
VALUES ('INV-1006', 'CA054BX18', 'V004', 'Northgate Civil', 'NCB-1180', '2025-05', 1743250.00, 'SUBMITTED');

-- ACECUN212: Table 1 current_phase = (Pre-Design), total_budget = $2,382,881.00, spend_to_date = $85,766.55
-- INV-1007: 15% of $2,382,881 = $357,432.15
INSERT INTO table_3_invoices (invoice_id, fms_id, vendor_id, vendor_name, invoice_number, billing_period, amount, payment_status)
VALUES ('INV-1007', 'ACECUN212', 'V005', 'Bayside Interiors & Finishes Inc.', 'BIF-2026-003', '2026-01', 357432.15, 'APPROVED');
-- INV-1008: 15% of $2,382,881 = $357,432.15
INSERT INTO table_3_invoices (invoice_id, fms_id, vendor_id, vendor_name, invoice_number, billing_period, amount, payment_status)
VALUES ('INV-1008', 'ACECUN212', 'V005', 'Bayside Interiors and Finishes', 'BIF-2026-119', '2026-01', 357432.15, 'SUBMITTED');

-- ACECUN214: Table 1 current_phase = (Pre-Design), total_budget = $1,383,851.00, spend_to_date = $47,948.93
-- INV-1009: 28% of $1,383,851 = $387,478.28
INSERT INTO table_3_invoices (invoice_id, fms_id, vendor_id, vendor_name, invoice_number, billing_period, amount, payment_status)
VALUES ('INV-1009', 'ACECUN214', 'V006', 'Kingsway Roofing and Waterproofing Co.', 'KRW-8802', '2025-09', 387478.28, 'APPROVED');

-- ACSPDF: Table 1 current_phase = (Pending), total_budget = $23,545,000.00, spend_to_date = $0.00
-- INV-1010: 7% of $23,545,000 = $1,648,150.00
INSERT INTO table_3_invoices (invoice_id, fms_id, vendor_id, vendor_name, invoice_number, billing_period, amount, payment_status)
VALUES ('INV-1010', 'ACSPDF', 'V007', 'Meridian HVAC Services Inc.', 'MHS-2026-0044', '2026-01', 1648150.00, 'SUBMITTED');
-- INV-1011: 9% of $23,545,000 = $2,119,050.00
INSERT INTO table_3_invoices (invoice_id, fms_id, vendor_id, vendor_name, invoice_number, billing_period, amount, payment_status)
VALUES ('INV-1011', 'ACSPDF', 'V007', 'Meridian H.V.A.C. Svcs', 'MHS-2026-0051', '2026-01', 2119050.00, 'SUBMITTED');

-- CROSSHVAC: Table 1 current_phase = (Pending), total_budget = $2,756,000.00, spend_to_date = $0.00
-- INV-1012: 33% of $2,756,000 = $909,480.00
INSERT INTO table_3_invoices (invoice_id, fms_id, vendor_id, vendor_name, invoice_number, billing_period, amount, payment_status)
VALUES ('INV-1012', 'CROSSHVAC', 'V007', 'Meridian HVAC Services Inc.', 'MHS-2025-0930', '2025-09', 909480.00, 'APPROVED');

-- BX024-011: Table 1 current_phase = (Completed), total_budget = $15,955,109.00, spend_to_date = $13,301,041.02
-- INV-1013: 10% of $15,955,109 = $1,595,510.90
INSERT INTO table_3_invoices (invoice_id, fms_id, vendor_id, vendor_name, invoice_number, billing_period, amount, payment_status)
VALUES ('INV-1013', 'BX024-011', 'V002', 'Hudson Mechanical Contractors Inc.', 'HMC-26-0107', '2026-01', 1595510.90, 'DENIED');

-- E23-0010: Table 1 current_phase = (Cancelled), total_budget = $6,561,080.96, spend_to_date = $0.00
-- INV-1014: 20% of $6,561,081 = $1,312,216.19
INSERT INTO table_3_invoices (invoice_id, fms_id, vendor_id, vendor_name, invoice_number, billing_period, amount, payment_status)
VALUES ('INV-1014', 'E23-0010', 'V001', 'Skyline Structural Group LLC', 'SKY-2026-0012', '2026-01', 1312216.19, 'DENIED');
-- INV-1015: 14% of $2,380,779 = $333,309.11
INSERT INTO table_3_invoices (invoice_id, fms_id, vendor_id, vendor_name, invoice_number, billing_period, amount, payment_status)
VALUES ('INV-1015', 'BX031-009', 'V003', 'Empire Electric Systems', 'EES-4502', '2026-01', 333309.11, 'SUBMITTED');
