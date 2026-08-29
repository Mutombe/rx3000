# Backlog — paused 29 Aug 2026

Parked mid-task to work on the owner's priorities. This is where to pick it up.

## What this work is

Two audits drive it, both in `qa/`:

- `qa/capability-gap.py` — endpoints where the screen sends **less** than the
  schema accepts. **Now at 0.**
- `qa/endpoint-coverage.py` — endpoints **no screen calls at all**. Was 38 when
  this started, now 20 of 353 routes (5%).

The pattern behind almost every finding: the deep version already existed on the
server, carefully written and documented, and the frontend either never called
it or built a shallower thing beside it.

## Uncommitted right now

Three files modified, typechecked clean, verified against the API, **not yet
committed**:

- `frontend/src/components/DiagnosisPicker.tsx` — a valid ICD-10 code the local
  table does not hold used to dead-end at "No matching diagnosis". The local
  table is a subset of the WHO release, and `/diagnoses/validate` exists to tell
  "no description held" from "not a real code". Now offers the code with the
  caveat. Also adds browsing by body system from `/diagnoses/chapters`.
- `frontend/src/pages/ProductDetail.tsx` — counselling points on the medicine
  record, from `/api/ai/counseling/{id}/stream`, which nothing could reach.
- `frontend/src/styles.css` — `.dx-chapter` for the chapter filter.

Verified: 22 chapters returned; a held code, a real-but-unheld code, and
nonsense each classified correctly; the chapter filter narrows and excludes.

**Next step: commit these three, then continue the list below.**

## Still unreached — the 20, triaged

### Worth a screen
- `POST /api/script-totals` — "the twelve figures the incumbent puts along the
  bottom of the script". Margin at dispensing time is how a dispenser notices
  they are about to sell below cost; in a report next month the medicine has
  gone. This is competitor-parity and probably the biggest one left.
- `GET /api/prescriptions/queue/unfinished` — scripts started and not finished,
  oldest first, "the stalest is the risk". No worklist shows them.
- `GET /api/products/barcode/{code}` — barcode lookup at the till.
- `GET /api/scan/codes/{product_id}`, `DELETE /api/scan/codes/{code_id}` —
  managing the barcodes a product answers to.
- `GET /api/repeats/due` — check first whether `/repeats/call-sheet`, which the
  Repeats page does call, already covers it.
- `GET /api/integrations` — what this pharmacy is connected to.
- `POST /api/remittances/fetch` — pull advices the funder published on the
  switch, rather than importing a CSV by hand.
- `GET /api/dispensing/stats`, `GET /api/system/licence` — check what they
  actually return before deciding.

### Probably fine unreached — confirm, then leave
- `GET /api/system/interactions/coverage` — the interaction screen already
  carries its coverage note in every response.
- `GET /api/fiscal/verify` — `/fiscal/status` already computes the chain result
  and the Fiscal page shows it.
- `GET /api/periods/postable/check`, `POST /api/ledger/backfill`,
  `GET /api/auth/demo/state` — internal or admin-only.
- `GET /api/currency/convert` — the rates are already on screen.
- `POST /api/marketing/consent/{patient_id}` — likely superseded by
  `/api/consent/{subject_type}/{subject_id}`, which `ConsentPanel` uses. If so,
  delete it rather than wire it, the way the duplicate interaction checker was
  deleted.
- `GET /api/pos/claims` — the Claiming page uses `/api/claiming/*`. Check for
  duplication.
- `POST /api/shifts/close` — the till uses `/shifts/{id}/cashup`. Check.

## UI quality — started 29 Aug, partly done

### Done
- **Payment dialog laid out in four columns.** `.tender-line` meant two
  incompatible things in one stylesheet and neither rule was scoped. Fixed and
  pinned by `qa/tender-modal.mjs` at five widths.
- **A PIN could not authorise anything** — the button tested `!password` in PIN
  mode and nothing submitted on the fourth digit. Both fixed; refusals now show
  at the top with the server's wording and clear the boxes.
- **Busy buttons showed nothing** unless the caller passed an icon. `.spin` was
  used in eight places and defined in none, so Refresh never spun either.
- **Dialogs are three regions now** — sticky title, scrolling body, sticky
  actions. `qa/modal-shell.mjs` proves the buttons are reachable without
  scrolling at 1440/1100/780.
- **`useOptimisticList`** — snapshot, generation guard, pending rows kept out of
  actions, motion for enter/exit. Applied to Stock departments.
  `qa/optimistic-list.mjs` covers both the success and the rollback.

### Still to do
- **Roll the hook out to the rest of the lists.** Only Stock departments uses it.
  Next by traffic: To-follows, Repeats, Orders, Patients, Leads, HelpDesk,
  Accounts, Deliveries, Will-call.
- **Update and delete paths are written but unexercised.** `update()` and
  `remove()` exist in the hook and no screen calls them yet; they need the same
  treatment `create` got — a real screen, a held-open network, and a refusal.
- **No empty flash on filter/page change.** `.is-refreshing` is in the
  stylesheet and nothing sets it. Lists still blank to a skeleton when a filter
  changes instead of dimming the rows already on screen.
- **Hover-to-prefetch** exists as `prefetchRoute` on some tables; it should be
  on all of them.
- **The POS split-tender panel is shallower than the shared component** — no
  wallet, no bank, no medical aid. Same class of gap as the part-payment modal
  had; it should use `Tenders`.
- **The branch scorecard clips every column** (screenshot 113706): twelve
  columns crammed, values truncated mid-word. Needs a real column strategy.

## Other outstanding

- **Rotate three exposed credentials.** A Neon Postgres connection string, a
  Render API key and an Anthropic API key are all in this conversation's
  history. Still not rotated. This is the only item here that is urgent.
- **Desktop build.** 1.4.2 is published and carries the Tenders and CRM work.
  Everything committed since — payments, sale reversal, bank reconciliation,
  approvals, exports, formularies — needs a 1.4.3 before it reaches an
  installed copy.

## Finished in this run

Each verified by a QA script, not by inspection.

| What | Verified by |
|---|---|
| CRM links: helpdesk tickets to accounts, contacts to owners and patients, a patient contact log | `qa/patient-contact-log.py` |
| Paying wholesalers, with invoice allocation and a printable remittance advice | `qa/supplier-payment.py` |
| Reversing a sale — void or fiscal credit note, whichever is lawful | `qa/sale-reversal.py` |
| Bank reconciliation, and the purchase half of "not posted" | `qa/bank-reconciliation.py` |
| Step-up approvals and refusals; every label reprint recorded | `qa/reprint-trail.py` |
| Seven datasets downloadable as spreadsheets | inline check, all seven |
| Formularies — what each scheme pays for | `qa/formulary.py` |

Two things were **deleted** rather than wired up, because a second shallower
implementation on a public API surface is worse than none: the duplicate
`/api/system/interactions/check`, which ignored the patient's medication history
— the case the whole module exists for.
