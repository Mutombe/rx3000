# Backlog — 30 Aug 2026

## Scores

| Audit | Score |
|---|---|
| `qa/capability-gap.py` — screens sending less than the schema accepts | **0** |
| `qa/endpoint-coverage.py` — endpoints no screen calls | **0 of 349** (was 38) |
| `qa/loading-states.py` — screens with no loading state | **0 of 68** (was 26) |

All three are pinned: the loading budget fails at one, and the coverage audit
now separates "no screen and should have one" from "no screen on purpose",
each of the latter named with its reason so the exemption can be argued with.

## What closed the last of it

**Given a screen** — barcode management on the product record (a code learned
against the wrong medicine was silent and permanent), the integrations panel on
System ("what is real and what is pretended, right now"), fetching remittance
advices from the switch, raising a delivery by hand, owing something to a
customer, posting a journal by hand, script totals, unfinished scripts.

**Deleted as shallower twins of something better** — nine in all:
`/system/interactions/check` (ignored the medication history), `/shifts/close`
(no denominations), `/marketing/consent` (overwrote a boolean with no
evidence), `/system/licence`, `/claiming/price`, `/dispensing/stats`,
`/pos/claims`, `/products/barcode/{code}` (a two-column match against a
resolver that reads symbology and pack multipliers), `/fiscal/verify`.

## Still open

- **`useOptimisticList.update()` is written and never called.** `remove()` is
  now exercised by the barcode panel; `update()` is not. Unproven code that
  looks finished.
- **Desktop 1.4.3.** 1.4.2 predates everything since: payments, sale reversal,
  bank reconciliation, the modal redesign, insurance standing, script totals,
  the repeat value work.
- **NH263 is not integrated**, so benefit balances are reported as unknown
  rather than known. That is honest, not finished.

## Urgent, and not mine to do

**Rotate three credentials.** A Neon Postgres connection string, a Render API
key and an Anthropic API key are all in this conversation's history. The Neon
one is live and has been used to write production data.
