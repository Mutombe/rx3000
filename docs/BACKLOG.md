# Backlog — 29 Aug 2026

## Scores

- `qa/capability-gap.py` — screens sending less than the schema accepts: **0**.
- `qa/endpoint-coverage.py` — endpoints no screen calls: **16 of 353 (4%)**,
  from 38 when this started.
- `qa/loading-states.py` — screens with no loading state: **16 of 68**, from 26.

## Done since the last revision

- **Script totals** — the dozen figures the incumbent prints along the bottom
  of a script, on the dispensary where the decision is. Margin included, with a
  below-cost warning said in words.
- **Unfinished scripts** — a fourth worklist segment. "Oldest first, the
  stalest is the risk", and nothing had ever shown them.
- **Insurance reconciliation** — whether the scheme is paying us, on the
  dispensary and in the till modal. Benefit balance says it is unknown rather
  than implying cover.
- **JIT patient form** — creatable wherever a search finds nobody.
- **Cash Office** — cash and mobile money in the headline, a per-wallet and
  per-bank breakdown matching the teller sheet, and petty cash finally records
  which drawer it came out of.
- **Till** — quick-settle now confirms currency and instrument; receipts print
  themselves on both settle and checkout.
- **Branch performance** — cards instead of twelve crammed columns, plus a
  detail page per branch with 39 figures.
- **Data loaded to production** — 14,455 patients, 45,728 sales worth
  668,699.08, one teller shift.
- **Four shallower twins deleted**: the duplicate interaction checker,
  `/shifts/close`, `/marketing/consent/{patient_id}`, and the second
  `/api/system/interactions/check`.

## Still open

### Worth doing
- **Roll `useOptimisticList` out.** Only Stock departments uses it. Its
  `update()` and `remove()` paths are written and unexercised — they need the
  same treatment `create` got: a real screen, a held-open network, a refusal.
- **16 screens still have no loading state** — `qa/loading-states.py` names
  them. POS, Stock, Leads, HelpDesk, Marketing and Admin are the busiest.
- **No dim while refetching** on ~12 screens. Checked: they do *not* blank —
  none clears its rows before fetching, so the important half is already right.
  What is missing is the feedback that a refetch is happening.
- **The POS split-tender panel is shallower than the shared `Tenders`** — no
  wallet, no bank, no medical aid. Same class of gap as the part-payment modal.
- **Hover-to-prefetch** is on some tables, should be on all.

### The remaining 16 unreached endpoints
Mostly internal or genuinely redundant. Worth a screen: `/api/integrations`,
`POST /api/remittances/fetch`, `/api/products/barcode/{code}` and
`/api/scan/codes/*` for barcode management. Confirmed redundant and left alone:
`/fiscal/verify` (status computes the chain), `/system/interactions/coverage`
(carried in every screening response), `/currency/convert` (rates are on
screen), `/repeats/due` (call-sheet covers it).

## Urgent, and not mine to do

**Rotate three credentials.** A Neon Postgres connection string, a Render API
key and an Anthropic API key are all in this conversation's history. The Neon
one is live and I have been using it to load production data. Still not rotated.

**Desktop build.** 1.4.2 predates everything since — payments, sale reversal,
bank reconciliation, the modal redesign, insurance standing, script totals.
Needs a 1.4.3.
