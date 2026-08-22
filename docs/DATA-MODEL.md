# Data model — the four tables the checks run on

> **Regenerate:** `node scripts/pull.mjs && node scripts/gen-csv.mjs`
> Seeded — two runs produce **byte-identical** files. An eval whose input drifts is not an eval.

**The grounding rule.** Every key, every phase and every vendor spelling is a **real published
value**. Only the invoice layer is generated, and each generated row points at a real budget line.
Nothing here invents a project, a key, or a company name.

| file | rows | what is real | what is not |
|---|---|---|---|
| `data/erp.csv` | 5,801 | **all of it** — `fb86-vt7u`, project view | `job_open_for_charges` is *derived*, not generated |
| `data/contracts.csv` | 5,801 | **all of it** — `fb86-vt7u`, finance view | `vendor_ids` — the one edge no public dataset supplies |
| `data/vendors.csv` | 986 | every spelling — from `n6ej-pebd` payees | the clustering and the ids |
| `data/invoices.csv` | 600 | `po_id`, `vendor_name` | the row itself |

---

## The join map

```
invoices.po_id ──────────► contracts.fms_id      (real key, 1:N)
                └────────► erp.fms_id            (real key, 1:N — 96 return conflicting phases)

invoices.vendor_name ────► vendors.aliases[]     (match on norm(), NOT on equality)
invoices.vendor_id ──────► vendors.vendor_id     (only after check 2 resolves)

contracts.vendor_ids ────► vendors.vendor_id     (generated edge)
invoices.doc_uri ────────► the rendered PDF      (check 1)
```

- **There is no invoice→budget join to get wrong.** The invoice carries `po_id`, which *is*
  `fms_id`. That is why checks 1–3 need no join at all.
- **The only real join is `po_id → fms_id`,** and it is **not one-to-one**: `fms_id` is 5,608
  distinct across 5,801 rows.

---

## `invoices.csv` — generated, every foreign key real

| column | type | source | notes |
|---|---|---|---|
| `invoice_id` | string | generated | PK, `INV-#####` |
| `po_id` | string | **real** `fb86-vt7u.fms_id` | FK → `contracts` and `erp` |
| `vendor_id` | string | generated | the answer check 2 must find. **Never read it as input** |
| `vendor_name` | string | **real** spelling from `n6ej-pebd` | 35% non-canonical by design |
| `amount` | decimal | generated | ≤ 7% of that line's real `total_budget` |
| `period` | `YYYYMM` | generated | inside the project's real schedule window |
| `status` | enum | generated | `paid` · `pending` · `denied` |
| `submitted_at` | date | generated | after `period` |
| `doc_uri` | path | generated | FK → the rendered PDF, for check 1 |
| `missing_field` | enum | generated | **ground truth for check 1** — which field was blanked, or `none` |
| `label_is_duplicate` | bool | generated | **ground truth for check 3** |
| `label_dead_job` | bool | derived | **ground truth for check 4** — from the row's real phase |

**`vendor_id` is the answer, not an input.** A resolver that reads it scores 100% and proves
nothing. Check 2 gets `vendor_name` and must reach `vendor_id` on its own.

### The planted duplicate — this is the demo

```
INV-00012  BED-807  paid     $130899.15  Public School 44
INV-00013  BED-807  pending  $130899.15  PUBLIC SCHOOL 44
```

Same PO, same amount, same period. **A literal name match finds nothing.** Check 2 resolves both to
`V0150`; only then does check 3 see it.

---

## `contracts.csv` — the finance view. Real, plus one generated edge

| column | type | source |
|---|---|---|
| `fms_id` | string | **real** — PK, receives `invoices.po_id` |
| `budget_line` | string | **real** |
| `total_budget` | decimal | **real** — caps `invoice.amount` |
| `spend_to_date` | decimal | **real** |
| `managing_agency` · `sponsor_agency` | string | **real** |
| `vendor_ids` | space-separated | **generated** — 1–3 per line |

**Why `vendor_ids` is generated:** no public NYC dataset ties a payee to a budget line. That edge
had to be created, and it is the only invented relationship in the finance table.

---

## `erp.csv` — the project view. Real, plus one derived column

| column | type | source |
|---|---|---|
| `pid` | string | **real** — 1:N with `fms_id`; blank on 2,356 rows |
| `fms_id` | string | **real** — receives `invoices.po_id` |
| `current_phase` | string | **real** — 36 distinct values |
| `current_phase_norm` | string | **derived** — parentheses and case stripped, 36 → **31** |
| `agency_project_name` | string | **real** |
| `forecast_completion` | date | **real** |
| `job_open_for_charges` | bool | **derived** — `(Completed)`/`(Cancelled)` → `false` |

**Two real defects live in this table, and neither was planted:**

| defect | measured | what check 4 must do |
|---|---|---|
| the phase enum is **aliased** | `Design`/`(Design)` · `Construction`/`(Construction)` · `(On-hold)`/`(On-Hold)` + 2 more | compare on `current_phase_norm`, never `current_phase` |
| one key, **conflicting phases** | **96** of 5,608 `fms_id`, carrying **$60,366,832,689**. `OFFSHRWND` is both `pending` and `pre-design` | **detect and COMMENT.** Never pick one |

---

## `vendors.csv` — derived from real payee spellings

| column | type | source |
|---|---|---|
| `vendor_id` | string | derived — PK |
| `canonical_name` | string | longest real spelling in the cluster |
| `alias_count` | int | derived |
| `aliases` | `\|`-separated | **every spelling real**, from `n6ej-pebd.organization` |

**48 of 986** carry more than one spelling. Those 48 are check 2's whole difficulty.

---

## Declared rates, and the assertion that guards them

| planted | declared | achieved at `--seed 42 --invoices 600` |
|---|---|---|
| duplicates | 0.08 | 41 |
| missing field | 0.10 | 72 |
| dead job | 0.12 | 79 |
| non-canonical spelling | 0.35 | 165 |
| **conflicting phases** | — | **96 — real, not planted** |

`gen-csv.mjs` **asserts every achieved rate within 35% relative and exits non-zero on a miss.**

**Why that assertion exists.** The first run planted **one** duplicate against a declared `0.08`:
only 48 of 986 vendors can alias, so the branch almost never fired. A stated rate nobody verified
gives every downstream eval a wrong denominator — which is the failure this whole project is about.

---

## Provenance

| claim | status |
|---|---|
| Every value in `erp.csv` and `contracts.csv` except `vendor_ids` | **published by NYC**, pulled 2026-08-22 |
| Every `po_id` and `vendor_name` in `invoices.csv` | **real published values** |
| The invoice rows themselves | **generated**, seeded, reproducible |
| 96 conflicting keys · 502 dead rows · 5 alias pairs | **measured** — `node scripts/findings.mjs` |
| 48 vendor clusters · $40,767,000 | **measured** — `node scripts/seed-aliases.mjs` |
| The four planted rates | **declared, then asserted** |
