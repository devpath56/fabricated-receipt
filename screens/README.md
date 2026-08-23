# screens/ — SECONDARY surface

**The primary product surface is the Streamlit app** (`app.py`, `app_with_mistral_chat.py`). That is
what runs the real checks, reads real invoices, and is what a reviewer should be shown first.

These files are a **static design reference**: one screen per check, every state each check can
actually reach, drawn on Agave's own design system. They exist to answer *"what should this look
like, and what states must it have?"* — not to run anything.

| file | what it is |
|---|---|
| `index.html` | all five screens in one page, with a state switcher. **This is the live link.** |
| `00-opening.html` | the room opener — kinetic, `N` / `B` / `space` |
| `check-1-intake.html` | intake · 5 required fields · gates checks 2-4 |
| `check-2-vendor.html` | vendor resolution · 0.90 merge floor, 0.75 suggest floor |
| `check-3-paid-before.html` | duplicate payment · block / clawback / review |
| `check-4-job-status.html` | job status · the six branches of `check_job_status` |
| `agave.css` | the shared token set |

## Why these are secondary, and still worth keeping

They render **states the app has to have and cannot show on demand** — a PO whose ERP records
contradict each other, a vendor that scores 0.86, a check that could not run at all. Reproducing
those live needs the right invoice in front of you. Here they are one click apart.

Every value is real: `INV-00012` / `INV-00013` are the planted duplicate pair, `OFFSHRWND` really
does return two phases, `SEQ200509` really is `(Completed)`.

## The distinction these screens exist to draw

`applicable` is **not** `outcome`. A COMMENT means one of two different things:

- the check **ran** and wants a human — coloured
- the check **could not run** and has no finding — **grey and dashed, never a warning colour**

A warning colour on an absent finding makes absence of evidence look like evidence. That is the
failure this whole project is named after.

## Design system

Measured from https://useagave.com with `getComputedStyle` across the whole DOM, not matched by eye.
Full package, with provenance: `~/.claude/skills/references/design-systems/design-md/agave/`.

Square corners (`border-radius: 0` everywhere), navy `#0F1B2E` product surfaces, green `#17CF60`
with black text on it, weights 400/600 only, every transition `.2s` on
`cubic-bezier(.075,.82,.165,1)`.

## Verified

- `state-matrix`: **23 of 23 declared states drawn, all four check screens PASS**
- `design-gate`: contrast and overflow clean at 375px and 1280px
