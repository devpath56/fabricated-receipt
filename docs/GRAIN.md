# GRAIN — what one row actually is

> **Why this file exists.** JTBD step 2's deterministic check is *"parse to AST; assert expected
> grain before execution."* You cannot assert a grain nobody wrote down. And you must not write one
> down from the publisher's description — that is exactly the thing this project exists to distrust.
>
> Everything below was **measured**, not read off a data dictionary. Reproduce with
> `node scripts/pull.mjs && node scripts/grain.mjs`.

---

## The headline

**Not one table in this project has a unique key.** Every candidate combination we tried collides,
including the column the publisher documents as the primary key.

> "Each row is uniquely identified by its Financial Management Service (FMS) ID. FMS ID is the
> unique ID that OMB uses for the FMS (Financial Information System). This ID can be universally
> joined with any OMB dataset that has the same field."
> — NYC Open Data, dataset description for `fb86-vt7u`

Measured: `fms_id` yields **5,608 distinct values across 5,801 rows.** 193 collisions.

The same paragraph then admits the opposite — *"FMS IDs and agency projects don't always have a
one-to-one relationship"* — and the dataset's own `rowLabel` gives a third answer,
*"unique project and budget line combination"*. Three statements, one dataset, and they cannot all
be true.

**This is not a complaint about NYC.** It is the normal condition of financial data in the wild, and
it is why "join on the obvious key" is a bug rather than a shortcut.

---

## Measured grain, table by table

### `budget_and_schedule` — `fb86-vt7u`

The bridge table. Budget, spend, phase, schedule, agency. Carries **both** identifiers.

| candidate key | distinct | of 5,801 | unique? |
|---|---|---|---|
| `fms_id` *(the documented PK)* | 5,608 | | **no** — 193 collisions |
| `pid` | 3,064 | | **no** — 1 project ↔ many FMS ids |
| `fms_id + budget_line` | 5,643 | | **no** |
| `pid + fms_id + budget_line` | 5,800 | | **no** — one exact duplicate on a 3-column composite |

- **One row is:** a project × FMS line × budget line, *approximately* — and the residual duplicate
  proves even that is not exact.
- **Assert before joining:** `pid` is **1:N**, never 1:1. A query that treats it as 1:1 fans out.
- 2,356 rows carry **no `pid` at all**, holding $64,836,845,710 — 31.2% of the period's dollars.
  An inner join drops them silently.
- Filter `reporting_period` or you get ten snapshots stacked. Period `202605` is the latest.

### `spend_history` — `qj5n-h5qp`

Monthly snapshots. The earliest snapshot for a line is its **original budget**; `budget_variance` is
the delta against the prior reported month. This is the original-versus-revised trail.

| candidate key | distinct | of 53,495 | unique? |
|---|---|---|---|
| `fms_id` | 5,645 | | **no** — expected, it is a time series |
| `fms_id + year_month_reported` | 52,910 | | **no** — 585 duplicate month-snapshots |
| `+ managing_agency` | 53,218 | | **no** — 277 still collide |

- **One row is:** a budget line's state as reported in one year-month — with **585 cases where the
  same line reports twice in the same month**. Nothing in the data says which is authoritative.
- **Assert before aggregating:** any `SUM` over this table without a `year_month_reported` filter
  double-counts across snapshots. This is the single easiest way to produce a confident wrong total.

### `capital_awards` — `n6ej-pebd`

Free-text recipient names and dollars. The **entity-resolution** surface.

| candidate key | distinct | of 1,256 | unique? |
|---|---|---|---|
| `organization` | 1,036 | | **no** — and see below |
| `fiscal_year + organization + capital_project` | 1,166 | | **no** — 90 exact duplicates |
| `+ community_district` | 1,166 | | **no** — the district adds nothing |

- **One row is:** an award of `funding` to `organization` for `capital_project` in `fiscal_year` —
  with 90 rows that are indistinguishable from another row on every field we have.
- **The alias problem, measured:** 1,036 raw names collapse to 986 under punctuation-and-case
  normalisation alone. **48 entities are spelled more than one way**, carrying **$40,767,000** —
  10.9% of the $374,735,000 total.

Real examples, published exactly like this:

```
PS 770 The New American Academy | PS 770-The New American Academy | PS 770, The New American Academy
P.S. 274 Kosciusko             | P.S. 274, Kosciusko             | P.S. 274 KOSCIUSKO
Brooklyn Bridge Park           | Brooklyn Bridge Park Corporation
Brooklyn Academy of Music, Inc. (BAM) | Brooklyn Academy of Music (BAM)
```

- **Recall is a lower bound.** `eval/vendor-aliases.seed.json` only catches differences of
  punctuation, case and legal suffix. Anything needing a similarity threshold is deliberately
  **not** in the seed — a seed that guesses teaches the wrong thing. Finding those is the resolver's
  job, and the seed is the floor it must clear, not the target.

### `project_schedules` — `2xh6-psuq`

Phase, status, and budget versus estimate versus actual spend. The **obligation-semantics** surface.

| candidate key | distinct | of 13,437 | unique? |
|---|---|---|---|
| `project_building_identifier` | 1,445 | | **no** |
| `+ project_phase_name` | 5,332 | | **no** |
| `+ project_type_` | 8,754 | | **no** — still 4,683 short |

- **One row is:** unresolved. No combination we tried identifies a row. Treat every aggregate over
  this table as suspect until a key is found or a de-duplication rule is agreed.

**The status enum is real and it is three values:**

| `project_status_name` | rows |
|---|---|
| `PNS` | 4,789 |
| `In-Progress` | 4,373 |
| `Complete` | 4,275 |

- **`PNS` is undefined in the data.** Neither the model nor we know what it means, and it is the
  **largest** bucket. Any total that includes it is asserting something nobody has established.
- **The check this justifies:** every dollar must carry a status; **refuse to total across mixed
  statuses without an explicit filter.** Adding `Complete` to `In-Progress` to `PNS` is a category
  error, not an arithmetic one — and no amount of SQL correctness catches it.

**Phases** (`project_phase_name`): `Construction` 6,299 · `Design` 1,967 · `Scope` 1,967 ·
`CM,F&E` 1,911 · `Purch & Install` 1,060 · `F&E` 177 · `CM,Art,F&E` 46 · `CM` 10.

- Three phase values **contain commas**. Any pipeline that round-trips through CSV without quoting
  will split them into new phantom categories. Cheap trap, real.

---

## The contract this file creates

Every query in this system asserts, before it executes:

| assertion | why |
|---|---|
| the expected **grain** of each table it touches | so "one row per project" is checked, not assumed |
| the expected **cardinality** of each join — `1:1` or `1:N`, declared | a 1:1 assumption that turns 1:N fans out and inflates every `SUM` |
| **unmatched rows and dollars**, returned on the answer | so a silent drop becomes a visible number |
| a **status filter** wherever a status column exists | so mixed-status totals cannot be produced by accident |

A query that cannot state these does not run.

---

## Provenance

| claim | how established |
|---|---|
| Every distinct-count in this file | `scripts/grain.mjs`, run against `data/*.json` pulled 2026-08-22 |
| The 48 alias clusters and $40,767,000 | `scripts/seed-aliases.mjs` → `eval/vendor-aliases.seed.json` |
| Status and phase distributions | counted over all 13,437 rows of `2xh6-psuq` |
| The quoted dataset description | read live from the Socrata metadata API |
| What `PNS` means | **unknown.** Not in the data, not guessed here |
