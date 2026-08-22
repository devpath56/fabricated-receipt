# The PM's invoice checklist — and which step each guard serves

> **Why this file exists.** Every guard in this project should trace to a step a real person
> currently performs by hand. This is that list. It is the **specification for the gold set**: a
> question worth grading is one that answers a step below.
>
> **The person.** A project manager at a general contractor, reconciling two systems that were never
> designed to agree:
>
> | system | holds | key |
> |---|---|---|
> | ERP — sanctioned project status, RBAC | is this project authorised, open, and how far along | **PID** |
> | Finance contract management DB | the contract, the money, what was billed | **FMS ID** |
>
> **Her whole job is one join nobody guaranteed: PID ↔ FMS ID.**

---

## A — Intake, before opening any system

| # | Step | Why it matters |
|---|---|---|
| A1 | Confirm it is an invoice, not a quote or a statement | Statements re-list already-paid items. Paying one double-pays everything on it |
| A2 | Read the invoice number; check the format matches this vendor's usual | A sudden numbering change means a re-issue, or someone else billing under their name |
| A3 | Read the invoice date **and the period covered** | Period governs, not date. A March invoice for February work belongs in February |
| A4 | Note the claimed contract / PO reference | The only thing tying paper to system. Often handwritten, often wrong |
| A5 | Pay application (% complete against a schedule of values) or straight invoice? | Different check paths entirely: field verification vs receipt confirmation |

## B — Who is this? *(vendor identity)*

| # | Step | What breaks |
|---|---|---|
| B1 | Search the vendor by name in the finance DB | Name on the letterhead is not the name in the system |
| B2 | If more than one match — decide: one entity, or several? | **The moment.** Two records means two payment histories, and the duplicate she will never see |
| B3 | Check remit-to bank details against the vendor master | A changed remit-to on an otherwise normal invoice is the leading payment-fraud vector |
| B4 | Insurance certificate current **as of the work period**, not as of today | Expired-at-time-of-work exposes the GC on any claim arising from that work |
| B5 | W-9 / tax status on file | Blocks at AP regardless; cheaper to catch here |
| B6 | Public work: certified payroll submitted for the period | Missing means payment legally cannot proceed |

**Measured in this repo's data** (`capital_awards`, `n6ej-pebd`): 48 entities carry more than one
spelling, holding **$40,767,000** — 10.9% of $374,735,000. Real, published exactly as shown:

```
ACME-style aliasing, real examples:
PS 770 The New American Academy | PS 770-The New American Academy | PS 770, The New American Academy
Brooklyn Bridge Park           | Brooklyn Bridge Park Corporation
Brooklyn Academy of Music, Inc. (BAM) | Brooklyn Academy of Music (BAM)
```

## C — Which money is this? *(the PID ↔ FMS ID join — her hardest step)*

| # | Step | What breaks |
|---|---|---|
| C1 | Look up the project in the **ERP by PID** — sanctioned and open? | A closed or unsanctioned PID means the money is not authorised at all |
| C2 | Look up the contract in the **finance DB by FMS ID** | Different system, different key, no guaranteed correspondence |
| C3 | **Find the PID ↔ FMS ID mapping** | ⚠️ No authoritative mapping exists. She rebuilds it from project name, agency, or memory |
| C4 | One PID returns several FMS IDs — decide which contract this invoice belongs to | Charge the wrong one and both budgets are now wrong, in opposite directions |
| C5 | FMS ID returns no PID — **stop** | Money with no sanctioned project behind it. She cannot approve, and often cannot explain why |
| C6 | Confirm the budget line and cost code the invoice should hit | Wrong code means the job that is losing money looks fine, and another job takes the hit |
| C7 | Confirm the fiscal period is open | A closed period forces an accrual — a different approval path entirely |

**Measured in this repo's data** (`budget_and_schedule`, `fb86-vt7u`, period `202605`):

| | |
|---|---|
| projects where **C4** fires | **207** of 3,063 — one PID mapping to as many as **14** FMS IDs |
| rows where **C5** fires | **2,356**, carrying **$64,836,845,710** — 31.2% of the period |
| `fms_id` distinct / rows | **5,608 / 5,801** — the documented primary key is not unique |

## D — Did the work actually happen?

| # | Step | What breaks |
|---|---|---|
| D1 | Pull the project status from the ERP | `Complete` · `In-Progress` · `PNS` |
| D2 | Status ambiguous or undefined → stop and ask | ⚠️ The **largest** bucket in our data (`PNS`, 4,789 rows) is undefined anywhere |
| D3 | Current phase matches what is being billed | Construction billing arriving during Design is a scope or coding error |
| D4 | Pay app: verify % complete per line against the schedule of values | The sub's 60% against the field's 40% — the most common dispute in the trade |
| D5 | Walk it, or call the superintendent, above a threshold | **The one step no system does for her** |
| D6 | Materials: delivery ticket signed on site | Billed-not-delivered is ordinary, not rare |
| D7 | Stored materials — on site, insured, documented? | Different payment rules; often paid without retention |
| D8 | Backcharges owed by this vendor | Damage, cleanup, another trade's rework. Net it here or lose it |

## E — Is the money there, and is this scope authorised?

| # | Step | What breaks |
|---|---|---|
| E1 | Original contract value on this FMS ID | The baseline |
| E2 | **Approved** change orders, summed | Approved only |
| E3 | **Pending** change orders — note them, exclude them | ⚠️ Billing against a pending CO is the classic overrun. It looks approvable and is not |
| E4 | Revised contract value = E1 + E2 | Never E1 + E2 + E3 |
| E5 | Previously billed to date on this contract | |
| E6 | This invoice + E5 ≤ E4? | If not, the invoice exceeds the contract. Stop |
| E7 | Committed vs actual vs forecast — is the budget line still funded? | A funded contract on an exhausted budget line still cannot be paid |

## F — Have we already paid this?

| # | Step | What breaks |
|---|---|---|
| F1 | Search this invoice number against this vendor | The easy duplicate |
| F2 | Search **same amount + same period across every spelling** of the vendor | ⚠️ The hard one. Depends entirely on B2 having been right |
| F3 | Did a prior pay application already cover these SOV lines? | Overlapping periods on pay apps are routine |
| F4 | Is this a re-issue of a previously rejected invoice? | Re-issues arrive with new numbers and identical content |

This is the **$68,000 rebar** failure: one invoice, two vendor records, both paid, caught by a person
reading a ledger rather than by the pipeline.

## G — Withholdings, before she signs

| # | Step |
|---|---|
| G1 | Apply retention at the contract rate — typically 5–10% |
| G2 | Confirm retention held to date matches the contract schedule |
| G3 | Conditional lien waiver for **this** payment received |
| G4 | Unconditional lien waiver for the **previous** payment received |
| G5 | Deduct backcharges from D8 |
| G6 | Apply any liquidated damages accrued |
| G7 | Net payable = invoice − retention − backcharges − LDs |

## H — Approve

| # | Step |
|---|---|
| H1 | Code to the PID, FMS ID, budget line and cost code established in C1–C6 |
| H2 | Confirm the amount is within her approval authority; route up if not |
| H3 | Attach the evidence — pay app, SOV, delivery tickets, waivers, CO references |
| H4 | Approve, recording **why**, not merely that |

---

## Where her time actually goes

| phase | routine invoice | exception |
|---|---|---|
| A · D · G · H | ~10 min | ~10 min |
| **B** — vendor identity | 2 min | **20–40 min** |
| **C** — PID ↔ FMS ID | 3 min | **30–90 min**, sometimes unresolved |
| **F** — duplicate hunt | 3 min | **20–60 min** |

- B, C and F are roughly **80% of her exception time and 100% of her risk**.
- All three are the same underlying problem: **an identifier she is told to trust that is not unique.**
- Durations are estimates from the workflow shape, not measured. Treat them as a hypothesis to test
  with a real PM, not as a finding.

---

## The mapping — every guard traces to a step

| her steps | job | the deterministic check | critical-path step |
|---|---|---|---|
| B1–B2 | 1 · entity resolution | candidate set must be exactly **1** after normalisation; if >1, halt and ask | 2 (Shivam) |
| C3–C5 | 3 · join without leaking | cardinality contract asserted pre-join; unmatched rows **and dollars** returned on the answer | 4 (Isha) |
| C6, E1–E7 | 2 · right grain | parse to AST; assert grain, filters and join type **before** execution | 3 (Shivam) |
| D1–D3, E2–E3 | 5 · obligation semantics | every dollar carries a status enum; **refuse** to total across mixed statuses without an explicit filter | 6 (Isha) |
| E6, F1–F4 | 4 · tie-out, fail closed | returned + dropped must equal the source total within tolerance, else refuse — never degrade | 5 (Isha) |
| every step | 6 · faithful rendering | narration graded against the **executed** AST; every claim maps to a clause | 7b (Shivam) |

**Deliberately not automated:**

| step | why it stays hers |
|---|---|
| D5 — walk it, or call the super | No system knows what was actually built |
| H4 — record *why* | The judgment is the approval. We supply the evidence, not the decision |

**What we remove is the searching** — B, C and F — which is where both the time and the errors live.

---

## How to use this file when writing the gold set

| rule | |
|---|---|
| 1 | A gold question must map to a **lettered step**. If it maps to none, it is a benchmark question, not a product question |
| 2 | At least one case per step in **B, C, E and F** — the four phases with measured failures behind them |
| 3 | Every case states the **expected refusal**, not only the expected answer. "Refuse, and say what did not tie out" is a correct answer |
| 4 | Seed from the failures we measured, not from questions that work. `eval/vendor-aliases.seed.json` is the floor for B, not the target |
| 5 | `PNS` cases exist and must **refuse** until someone tells us what `PNS` means |
