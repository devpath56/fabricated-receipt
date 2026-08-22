# Table 3 — the invoice ledger the checks run against

> Handoff for the invoice-validation demo. Everything here was read from the two live NYC datasets
> on 2026-08-22; nothing about the projects is recalled or estimated. Companion to
> [`PROPOSAL.md`](./PROPOSAL.md), whose Decision 05 and Decision 06 this extends.

**What this adds to the proposal.** Decision 06 proved the join is broken in two ways. Those are
failures of *aggregation*. This is the layer above: a submitted invoice, and three checks that have
to answer before money moves.

| # | Check | Answered from |
|---|---|---|
| 1 | **Job status** — is this `fms_id` on a currently valid project? | Table 1 `current_phase` |
| 2 | **Vendor resolution** — does the name on the invoice match the party we think it is? | Table 3 `vendor_id` vs `vendor_name` |
| 3 | **Duplicate payment** — has this, or an equivalent, already been paid? | Table 3, against itself |

---

## Decision 10 — The key is a string, and it is not unique

### A schema that declares `fms_id INTEGER` throws away five of the six formats in the file.

Measured over all 56,525 rows of [`fb86-vt7u`](https://data.cityofnewyork.us/d/fb86-vt7u):

| measure | value |
|---|---|
| rows / distinct FMS IDs | 56,525 / **8,171** |
| reporting periods | 10 — `202305` … `202605` |
| distinct (Reporting Period, FMS ID) pairs | **54,865** of 56,525 |
| newest period alone | 5,801 rows carrying 5,608 distinct FMS IDs |
| ID length | 5 to 9 characters |

Real IDs, copied verbatim: `MC024-008` · `E23-0010` · `CA054BX18` · `BXELEVFAR` · `ACSPDF` ·
`JJCONS` · `61608113`.

**Two consequences a reviewer should check first.**

1. `fms_id` is `VARCHAR(16)`. An `INTEGER` column silently drops every ID that is not all digits —
   which is most of them.
2. **A foreign key to Table 1 cannot be declared.** No column set in that file is both unique and
   equal to `fms_id`; the pair `(Reporting Period, FMS ID)` is not unique either. This is the same
   fan-out Decision 06 measured, arriving at DDL time. The schema references a materialised
   `table_1_current_projects` view — one row per `fms_id` from the newest period — rather than
   inventing a surrogate key or pretending the constraint holds.

---

## Decision 11 — "Active" is a typographic convention, not a field

### Table 1 has 61 distinct `current_phase` values, and the parenthesis carries the meaning.

| shape | meaning | examples (row counts, all periods) |
|---|---|---|
| bare | a real work phase | Construction 7,837 · Design 6,625 · Close-out 4,420 · Construction Procurement 3,762 |
| `(parenthesised)` | a state, not work | (Pending) 12,145 · (Completed) 4,854 · (Cancelled) 788 · (On-Hold) 464 |

**The casing does not hold, and check 1 must absorb that:**

| concept | spellings in the file |
|---|---|
| cancelled | `(Cancelled)` 788 · `(cancelled)` 28 · `(CANCELLED)` 1 |
| on hold | `(On-Hold)` 464 · `(On-hold)` 304 · `(On Hold)` 1 |
| construction | `Construction` 7,837 · `CONSTRUCTION` 1 |
| construction procurement | `Construction Procurement` 3,762 · `Construction procurement` 52 |

So the check matches on `lower(current_phase)` **and** the leading `(` — never on a literal list of
phase names. A hand-typed list of "valid phases" is how this check goes quietly wrong in month two.

---

## Decision 12 — The demo data

### 15 invoices, 10 real project IDs, and four planted failures.

Four files, and the split between the last two is deliberate:

| file | what it is |
|---|---|
| [`sql/table_3_invoices.sql`](../sql/table_3_invoices.sql) | the DDL |
| [`sql/table_3_invoices_data.sql`](../sql/table_3_invoices_data.sql) | the 15 rows as INSERTs, with the per-invoice grounding as comments |
| [`data/table_3_invoices.csv`](../data/table_3_invoices.csv) | the same 15 rows, 8 columns, nothing else — **this is what the pipeline reads** |
| [`data/table_3_answer_key.csv`](../data/table_3_answer_key.csv) | 45 rows: every invoice x every check, with the expected verdict |

**The answer key is a separate file on purpose.** A column of expected verdicts sitting inside the
invoice CSV is an answer leaking into the model's input. Ground truth is only ground truth while
the thing being graded cannot see it.

| `INV-1001` | `MC024-008` | `V001` | Skyline Structural Group LLC | `SKY-2025-0417` | `2025-05` | $286,731.96 | PAID |
| `INV-1002` | `MC024-008` | `V001` | **Skyline Structural Grp.** | `SKY-2025-0488` | `2025-09` | $191,154.64 | APPROVED |
| `INV-1003` | `YC002-023` | `V003` | Empire Electrical Systems Corp. | `EES-4471` | `2025-09` | $330,000.00 | SUBMITTED |
| `INV-1004` | `BX031-009` | `V002` | Hudson Mechanical Contractors Inc. | `HMC-25-0912` | `2025-09` | $714,233.81 | PAID |
| `INV-1005` | `CA054BX18` | `V004` | Northgate Civil Builders LLC | `NCB-1180` | `2025-05` | $1,743,250.00 | PAID |
| `INV-1006` | `CA054BX18` | `V004` | **Northgate Civil** | `NCB-1180` | `2025-05` | $1,743,250.00 | SUBMITTED |
| `INV-1007` | `ACECUN212` | `V005` | Bayside Interiors & Finishes Inc. | `BIF-2026-003` | `2026-01` | $357,432.15 | APPROVED |
| `INV-1008` | `ACECUN212` | `V005` | **Bayside Interiors and Finishes** | `BIF-2026-119` | `2026-01` | $357,432.15 | SUBMITTED |
| `INV-1009` | `ACECUN214` | `V006` | Kingsway Roofing and Waterproofing Co. | `KRW-8802` | `2025-09` | $387,478.28 | APPROVED |
| `INV-1010` | `ACSPDF` | `V007` | Meridian HVAC Services Inc. | `MHS-2026-0044` | `2026-01` | $1,648,150.00 | SUBMITTED |
| `INV-1011` | `ACSPDF` | `V007` | **Meridian H.V.A.C. Svcs** | `MHS-2026-0051` | `2026-01` | $2,119,050.00 | SUBMITTED |
| `INV-1012` | `CROSSHVAC` | `V007` | Meridian HVAC Services Inc. | `MHS-2025-0930` | `2025-09` | $909,480.00 | APPROVED |
| `INV-1013` | `BX024-011` | `V002` | Hudson Mechanical Contractors Inc. | `HMC-26-0107` | `2026-01` | $1,595,510.90 | DENIED |
| `INV-1014` | `E23-0010` | `V001` | Skyline Structural Group LLC | `SKY-2026-0012` | `2026-01` | $1,312,216.19 | DENIED |
| `INV-1015` | `BX031-009` | `V003` | **Empire Electric Systems** | `EES-4502` | `2026-01` | $333,309.11 | SUBMITTED |

Bold `vendor_name` = a deliberate variant of the canonical name for that `vendor_id`.

### Grounding — every row below read from Table 1, reporting period `202605`

| `MC024-008` | Design | $1,592,955.31 | $71,955.31 | 2 | PASS |
| `YC002-023` | Design | $1,500,000.00 | $0.00 | 1 | PASS |
| `BX031-009` | Construction | $2,380,779.36 | $2,380,779.36 | 2 | PASS |
| `CA054BX18` | Construction | $6,973,000.00 | $4,229,239.94 | 2 | PASS |
| `ACECUN212` | (Pre-Design) | $2,382,881.00 | $85,766.55 | 2 | PASS |
| `ACECUN214` | (Pre-Design) | $1,383,851.00 | $47,948.93 | 1 | PASS |
| `ACSPDF` | (Pending) | $23,545,000.00 | $0.00 | 2 | PASS |
| `CROSSHVAC` | (Pending) | $2,756,000.00 | $0.00 | 1 | PASS |
| `BX024-011` | (Completed) | $15,955,109.00 | $13,301,041.02 | 1 | **FAIL** |
| `E23-0010` | (Cancelled) | $6,561,080.96 | $0.00 | 1 | **FAIL** |

- Largest invoice is **33%** of its project's total budget; none exceeds it.
- `2025-05` · `2025-09` · `2026-01` each exist as a `Year-Month Reported` in
  [`qj5n-h5qp`](https://data.cityofnewyork.us/d/qj5n-h5qp) for the IDs they are used with.

---

## Decision 13 — The answer key

### For the demo script. Not for the model being evaluated.

| invoice_id | check it should trigger | why |
|---|---|---|
| `INV-1013` | **Job status FAIL** | `BX024-011` is `(Completed)` |
| `INV-1014` | **Job status FAIL** | `E23-0010` is `(Cancelled)` |
| `INV-1006` | **Duplicate — obvious** | identical `NCB-1180` / `CA054BX18` / `2025-05` / $1,743,250.00 to `INV-1005`, which is **PAID** |
| `INV-1008` | **Duplicate — fuzzy** | a different invoice number, but the same project, vendor, month and amount as `INV-1007` |
| `INV-1002` `INV-1006` `INV-1008` `INV-1011` `INV-1015` | **Vendor mismatch** | correct `vendor_id`, drifted name — abbreviation, `&`→`and`, dropped suffix, punctuation |
| `INV-1013` | second signal | spend to date is already **83%** of budget on a completed project |
| the other 8 | clean | active phase, canonical name, no equivalent row |

---

## Decision 14 — The schema rejects the duplicates, and that is a choice to make out loud

### With the constraints on, the database answers before the check runs.

`table_3_invoices` declares:

```sql
CONSTRAINT uq_vendor_invoice_number UNIQUE (vendor_id, invoice_number)
CONSTRAINT uq_equivalent_invoice    UNIQUE (fms_id, vendor_id, billing_period, amount)
```

`INV-1006` violates the first. `INV-1006` and `INV-1008` violate the second. **That is the
constraints working** — and it makes check 3 unreachable, because the bad rows never land.

| | **(a) demo the CHECK** | **(b) demo the SCHEMA** |
|---|---|---|
| constraints | dropped to plain indexes | left on |
| rows loaded | 15 | 13 |
| what the audience sees | the validator catching a paid duplicate | Postgres raising `23505` at INSERT |
| what it proves | the thing we are building | that a well-specified table needs no validator |
| answer key above assumes | **this one** | — |

The data file opens with the two `ALTER`s for (a). **This is a real product question, not a
plumbing detail:** if duplicate payment is preventable by a unique constraint, the interesting
product is the *fuzzy* case — `INV-1008` — which no constraint catches, because a resubmission
under a new invoice number is a different row by every exact-match definition.

---

## What is grounded, and what is not

| element | source |
|---|---|
| `fms_id`, `current_phase`, `total_budget`, `spend_to_date` | Table 1, `fb86-vt7u`, period `202605` |
| `billing_period` values | Table 2, `qj5n-h5qp`, real `Year-Month Reported` for those IDs |
| `amount` | computed as a stated percentage of that ID's real total budget |
| `vendor_id`, `vendor_name`, `invoice_number`, `invoice_id` | **invented.** Neither dataset has a vendor column — all 27 Table 1 columns and all 8 Table 2 columns were scanned |

**Three findings that a cleaner-looking schema would have hidden:**

| finding | consequence for the demo |
|---|---|
| **94 projects have `total_budget` ≤ 0** in the newest period; smallest positive is $14, median $5,130,107 | "amount is a plausible fraction of budget" has no denominator there. The check must return UNEVALUABLE, never PASS |
| **8 of 5,645** Table 2 FMS IDs do not appear in Table 1 | the T1↔T2 join is not total, so a missing budget context is not the same as a bad invoice |
| **39 FMS IDs carry more than one Managing Agency** in the newest period | "who owns this project" is itself ambiguous before vendor resolution starts |

---

## Reproduce

```bash
curl -sL "https://data.cityofnewyork.us/api/views/fb86-vt7u/rows.csv?accessType=DOWNLOAD" -o t1.csv
curl -sL "https://data.cityofnewyork.us/api/views/qj5n-h5qp/rows.csv?accessType=DOWNLOAD" -o t2.csv
```

Every count in this document comes from those two files, filtered to `Reporting Period == 202605`
where a current-state claim is made.

---

## Still open

| question | who decides |
|---|---|
| (a) or (b) in Decision 14 — is the demo about the check or the schema? | product |
| Should `table_1_current_projects` be a materialised view or a nightly load? 10 periods exist and the newest wins; nothing yet decides what happens when a project disappears between periods | eng |
| Vendor resolution has no data to resolve against. A real `vendor_master` would give it work; inline `vendor_id` means the demo compares two columns in one row | product |
| The 94 non-positive budgets and the 39 multi-agency IDs are real rows a live pipeline hits. Are they in scope, or filtered out with the filter stated? | product |
