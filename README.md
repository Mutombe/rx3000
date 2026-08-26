# RX5000 — Pharmacy Management System

Full pharmacy suite: dispensing, point of sale, stock control, electronic
schedule register, repeat/reminder automation, medical aid claiming, reporting,
and a Claude-powered AI bloodstream (interaction checks, patient summaries,
natural-language business Q&A).

## Stack

- **Backend** — Python / FastAPI / SQLAlchemy / SQLite (`backend/`), APScheduler for reminder jobs, Anthropic SDK (`claude-opus-5`) for AI features
- **Frontend** — React / Vite / TypeScript (`frontend/`), glassy frosted-card design system

## Design system — "quiet precision"

Restraint is what reads as expensive. Surfaces are near-opaque with hairline
borders rather than glow, hierarchy is carried by type and spacing rather than
ornament, and colour is reserved for meaning. Everything in
`frontend/src/styles.css` is a scale — **nothing in a page should invent a size,
a radius or a shadow.** If a value is missing, it gets added to the scale.

| Scale | Tokens |
|---|---|
| Spacing (4pt) | `--s1` 4px … `--s12` 48px |
| Radius | `--r-sm` 6 · `--r-md` 8 · `--r-lg` 12 · `--r-xl` 16 · `--r-pill` |
| Elevation | `--e1` `--e2` `--e3` — three levels, all subtle |
| Control height | `--control-sm` 30 · `--control` 38 · `--control-lg` 44 |
| Type | `--t-xs` 11 … `--t-2xl` 30 |

**Figures are Inter tabular, not a display face.** Money has to align in a
column and be read at a glance; novelty numerals do neither. `tabular-nums` and
`lining-nums` are applied to every `.num` cell, stat value and figure. IBM Plex
Mono is reserved for codes — invoice numbers, barcodes, auth codes, hashes.

**Form fields are guarded.** `components/Field.tsx` owns the label, hint, error
slot and width; rows are a 12-column grid where a field declares `span` rather
than the page hard-coding a pixel width. That inversion is what stops control
sizing drifting — the earlier UI had ~140 inline style escapes patching around
components that had no size discipline of their own.

**Dropdowns fold.** `components/Select.tsx` replaces the native `<select>`,
which cannot be styled consistently across browsers and renders an OS list on
Windows that ignores the design system entirely. It is portal-positioned,
flips above the trigger when there is no room below, matches the trigger width,
becomes searchable past eight options, supports option hints and groups, and is
fully keyboard-driven (↑/↓, Enter, Esc, Home/End, type-to-filter). Native
selects not yet converted are styled to match as a fallback.

## Brand

The RX5000 mark lives in `frontend/public/logo.png` (with `favicon.png` and
`apple-touch-icon.png` derived from it) and appears in the sidebar, on the login
card, as the browser favicon and on printed tax-invoice receipts.

The palette is taken straight from the mark — blush rose flowing through mauve
into deep indigo — and is exposed as CSS variables in `frontend/src/styles.css`:

| Variable | Value | Used for |
|---|---|---|
| `--indigo` | `#3b3e56` | Primary buttons, active nav/tabs, deep end of every gradient |
| `--accent` | `#6a6485` | Gradient partner, chart fills, focus states |
| `--mauve` | `#97829c` | Mid-tone ambient wash, input focus ring |
| `--rose` | `#f0b4b6` | Active nav icons, chart tops, drop-target highlight |
| `--blush` | `#fadcde` | Default badge fill, light end of hero tiles |

Semantic status colours (`--ok`, `--warn-soft`, `--danger`) are deliberately kept
outside the brand palette so success/warning/error states stay unambiguous.

## Quick start

```powershell
# 1. Backend  (http://localhost:8177)
cd backend
pip install -r requirements.txt
copy .env.example .env          # optionally add ANTHROPIC_API_KEY, SMTP, SMS gateway
python -m uvicorn app.main:app --port 8177

# 2. Frontend (http://localhost:5180)
cd frontend
npm install
npm run dev
```

Open **http://localhost:5180** and sign in:

| Username     | Password  | Role        |
|--------------|-----------|-------------|
| `admin`      | admin123  | Admin       |
| `pharmacist` | pharm123  | Pharmacist  |
| `cashier`    | cash123   | Cashier     |

The database (`backend/rx5000.db`, or an existing `rx3000.db` if one is already
there) is created and seeded automatically on
first run: demo users, medical aids, doctors, suppliers, a product catalogue
across schedules S0–S6, and three patients.

## Module names

The navigation uses trade-standard module names rather than descriptive labels.
Route paths are unchanged, so the mapping is only skin-deep:

| Module | Route | Covers |
|---|---|---|
| Command Centre | `/` | Live operational overview |
| Dispensary · Controlled Register · Patient Adherence | `/dispense` `/register` `/reminders` | Clinical |
| Front Shop · Cash Office · Inventory · Procurement | `/pos` `/shifts` `/stock` `/orders` | Retail |
| Leads · Opportunities · Accounts · Campaigns · Cases · Revenue Intelligence | `/leads` `/pipeline` `/accounts` `/marketing` `/helpdesk` `/crm-reports` | Revenue |
| Analytics · Pulse AI · Control Panel | `/reports` `/assistant` `/admin` | Intelligence |

## Jurisdiction packs

RX5000 is sold into more than one country, and nearly everything that differs
between them is regulatory rather than functional. Each country is a pack in
`backend/app/jurisdictions.py`, selected with one setting:

```ini
JURISDICTION=ZA     # South Africa (default)
JURISDICTION=ZW     # Zimbabwe
```

A pack supplies the medicine schedules and their dispensing rules, the medicines
regulator, the privacy statute governing marketing consent, the product-code
label, the ID label recorded in the controlled register, locale, currencies, VAT
rate, tax-year start, the local medical schemes, and whether receipts must be
fiscalised. `GET /api/jurisdiction` exposes all of it so the front end reads
labels and currency instead of hard-coding a country.

Dispensing, repeats, FEFO, stock, procurement, CRM and the till are
jurisdiction-neutral and never change. Adding a country means adding a pack.

**Dispensing routes are the stable contract.** Every pack maps its schedules to
`otc | prescription | controlled | prohibited`; the schedule numbers behind each
route differ by country, so callers ask `schedules_for_route()` rather than
assuming. VAT and currency fall back to the pack unless `VAT_RATE` or `CURRENCY`
is set explicitly.

> **The Zimbabwe pack is a draft.** Its schedule model has not been verified
> against MCAZ's current classification and is marked `verified=False` with a
> caveat the app surfaces rather than passing silently. Confirm the schedules,
> repeat limits and controlled-substances register format before dispensing
> against it. ZIMRA fiscalisation is declared by the pack but **not implemented** —
> a VAT-registered Zimbabwean pharmacy cannot legally run this as a till until it is.

## AHFoZ clearinghouse gateway

A single gateway in front of Zimbabwe's funders. One unified payload goes in;
whichever wire format the destination switch speaks comes out.

```
POST /auth/token            OAuth2 client credentials -> bearer token
POST /eligibility/verify    real-time benefit check
POST /claims/submit         unified claim, routed and adjudicated
GET  /gateway/funders       registered funders and their switch routing
GET  /gateway/tariffs       the active AHFoZ tariff book
GET  /gateway/errors        the published error contract
GET  /gateway/transactions  audit trail
```

**The value is not the transport — it is what happens before it.**

*Reject early.* Tariff and ICD-10 errors are caught at the gateway, where they
cost nothing. The same error caught by a switch costs a round trip, a
resubmission, and often a fortnight of the money not arriving. Validated before
routing: ICD-10 structure *and* existence *and* expiry; tariff code against the
active book; unit price inside the negotiated band; line maths; header total
against the sum of lines; and claim currency against the funder's pool.

*One error vocabulary.* Switches return wildly variable strings for the same
condition, so the gateway maps everything onto fixed codes and statuses:

| HTTP | Code | Trigger |
|---|---|---|
| 400 | `INVALID_ICD10` | Diagnosis malformed, unknown or expired |
| 400 | `UNKNOWN_FUNDER` / `VALIDATION_FAILED` | Unregistered funder, payload inconsistent |
| 402 | `MEMBER_SUSPENDED` | Funder reports premiums in arrears |
| 422 | `TARIFF_MISMATCH` / `TARIFF_UNKNOWN` | Price outside band, or code not in the book |
| 422 | `CURRENCY_MISMATCH` | Claim currency is not the funder's pool currency |
| 502 | `SWITCH_UNAVAILABLE` | Switch unreachable or adapter absent |
| 504 | `SWITCH_TIMEOUT` | No reply within 15 seconds |

Rejections name the offending `line_number` where one applies.

*Keep the evidence.* Every call — success or rejection — is recorded with the
request, the response, the error code, the references and the duration, because
a funder query six months later is answered from the record, not from memory.

**Routing.** A funder carries a default switch; the payload may override it with
`switch_destination`. Adapters are `SIMULATOR`, `HEALTH_263`, `MEDISWITCH` and
`DIRECT`.

> **The Health 263 and Mediswitch adapters are not implemented.** The gateway
> contract is settled, but what each switch expects on the wire is not, and is
> not guessed at: Health 263 needs its REST specification, Mediswitch needs the
> WSDL, the SOAP envelope and the fault-code list so faults can be mapped onto
> the error codes above. Everything around them — validation, routing, error
> normalisation, audit — is finished and proven against the simulator. Each is
> one class.
>
> The seeded tariff prices are **illustrative**. The real AHFoZ book is
> published per financial year and must be loaded before claiming: a wrong band
> rejects every claim that touches it.

## Medical aid claiming

A pharmacy earns most of its revenue from schemes, so claiming is the entry
fee — everything else is optional next to it.

**Prices are derived, never typed.** A dispensed price is built from the single
exit price plus a professional fee that steps by price band, then capped,
discounted and levied per scheme. Typing a price by hand is how a pharmacy ends
up short-paid or over-claiming. `services/pricing.py` computes it in the order a
scheme audits:

1. **base** — single exit price × quantity
2. **reference-price cap (MMAP)** — where a scheme prices generics off a
   reference price, the medicine portion is capped, the patient pays the
   difference, and **that difference is never claimable**
3. **professional fee** — from the price band, charged on the *capped* amount
4. **scheme markup**, then **scheme discount**
5. **patient levy** — fixed or a percentage, whichever the scheme uses
6. **claim** — what the scheme is asked to pay

**Fee bands are data, not code.** They are set by regulation and revised; a
revision must not require a release. A model has any number of bands with a
percentage, fixed fee, floor and ceiling, plus one open-ended top band.

> The seeded fee bands are **illustrative placeholders** shaped like a real
> regulated schedule. They are not gazetted figures — load the actual bands for
> the jurisdiction before claiming against them.

**ICD-10** is on the script line, because a claim line without a diagnosis is
rejected. `GET /api/claiming/diagnoses?q=` is a type-ahead over code and
description. The seed is a working starter set; a live install imports the full
ICD-10 release.

**Pay offices** are who actually settles — several schemes are administered and
paid by one office, so claims batch and reconcile per office rather than per
scheme. Each scheme carries its own fee model, levy, discount, extra markup,
currency variant, biometric requirement and whether it claims realtime or by
batch.

**Formulary coverage.** A scheme rejecting a line at claim time is the worst
moment to find out — the medicine has left the shelf and the patient has left
the shop. So coverage is checked *before* dispensing:
`POST /api/claiming/coverage` returns a verdict per line — `covered`,
`reference`, `authorisation` or `excluded` — with quantity limits and the reason.

A formulary's `default_rule` decides what happens to an unlisted product: an
**open** formulary pays unless told otherwise, a **closed** one pays only what
is listed. Getting that backwards is the difference between over-claiming and
rejecting everything.

**A verdict alone is not useful.** "Not covered" leaves the pharmacist stuck, so
the check also returns **covered alternatives sharing the same active
ingredient**, cheapest first, with the saving. That turns a rejection into a
substitution. Matching is on the molecule and is deliberately strict: a
combination product is a different molecule from its single agent, so
amoxicillin is never offered as a substitute for amoxicillin/clavulanate. That
would be a clinical error, not a pricing one.

**Batching.** Realtime schemes settle line by line and are deliberately excluded
from batches — batching them would double-claim. Everything else gathers into a
numbered batch per pay office, submits, and then settles against a remittance.
Short payment is the normal case, so the shortfall is **reported, not silently
absorbed** — that difference is what gets queried with the scheme.

## Compounding

An extemporaneous preparation is assembled from stock at the moment it is
needed, which makes two things true that a shelf product never has to worry
about.

**Its cost is the sum of what went into it**, plus the labour — nothing on a
price file describes it. `GET /api/compounding/mixtures/{id}/cost` totals the
ingredients at their cost price, adds the compounding fee, scales with the batch
count, and reports whether stock actually allows it before anything is drawn.

**Its schedule is the highest schedule of any ingredient.** A cream containing a
controlled substance *is* a controlled substance. Treating the compound as a
cream would let a Schedule 5 walk out of the shop without a register entry, so
the schedule is derived rather than typed, the ingredient responsible is named,
and preparing one returns an explicit warning to dispense it under that
schedule's rules.

Preparing draws ingredients through the ordinary FEFO path, so a compound never
quietly bypasses batch tracking or expiry, and the result carries an expiry
derived from the recipe's shelf life.

## Keyboard-first dispensing

A dispensary runs hundreds of scripts a day and the pharmacist never reaches for
the mouse. The incumbent drives an entire script from function keys; matching
that is not a nicety, it is the difference between being adopted and being
rejected on the stopwatch.

| Key | Action |
|---|---|
| `F2` | Find patient |
| `F3` | Add medicine |
| `F4` | Diagnosis |
| `F6` | Interaction check |
| `F8` / `F9` | Repeats due / Recent scripts |
| `F12` | Dispense |
| `Esc` | Clear the script |
| `?` | Show the key map |

Rules that keep shortcuts from becoming a hazard, in `hooks/useHotkeys.ts`:
function keys fire **even while typing**, because that is where the
pharmacist's hands already are; plain-letter shortcuts never fire mid-typing;
a disabled action is skipped rather than silently doing nothing; and every
binding carries a label, so **the key map and the bindings are generated from
one declaration** — a shortcut cannot exist without being documented, or be
documented without working. The same declaration renders the always-visible
key bar along the bottom of the dispensing screen.

## Fiscalisation

Where a revenue authority requires fiscalised receipting, the jurisdiction pack
declares the regime and the fiscal layer engages automatically. Where it does
not, nothing is written and no receipt is queued.

The mechanics are the same in every regime and are implemented in full:

- **Fiscal days.** Trading happens inside an open day; closing it files the
  Z-report totals. A sale after close opens the next day automatically and the
  per-day receipt counter restarts.
- **Two counters.** A per-day counter that resets and a global counter that
  never does — gaps in either are what an auditor looks for.
- **A hash chain.** Each receipt is a SHA-256 over a canonical string of its own
  contents plus the previous receipt's hash. `GET /api/fiscal/verify` walks the
  chain and names the first break. Editing or removing a filed receipt is
  detectable, which is the entire point.
- **Queue, don't block.** If the authority is unreachable the receipt is still
  written, hashed and chained locally, then filed on reconnection. A till that
  stops selling when the network drops is worse than a late filing. A day cannot
  be closed while receipts are still queued, since that would understate the
  Z-report.
- **No voids, only credit notes.** Once accepted a receipt cannot be withdrawn.
  `POST /api/pos/sales/{id}/void` refuses a fiscalised sale and points at
  `POST /api/fiscal/credit-note/{id}`, which files a linked reversing receipt.
  Double reversal is refused.

Device drivers are pluggable (`services/fiscal_devices.py`), same pattern as the
card terminals: `none`, `simulator`, and `zimra_fdms`.

> **The ZIMRA FDMS driver is deliberately not implemented.** Getting a
> compliance integration wrong is worse than not having one, so the wire
> protocol is not guessed at. What is needed from ZIMRA's published FDMS
> specification is listed in the driver's docstring: device registration and
> certificate, the request signing scheme, endpoint URLs and payload schema, the
> day open/close shape, and the QR payload format. Everything around it is built
> and proven against the simulator — implementing that one class is the
> remaining work. Until then a Zimbabwean till accumulates a valid local chain
> but **is not filing with ZIMRA and is not compliant.**

## Money and currency

A pharmacy in a dual-currency market prices in one currency of account and takes
payment in several. Three rules keep the books honest, and the code enforces
them rather than relying on discipline:

1. **Line prices are held in the base currency.** Converting on display is safe;
   converting on storage compounds rounding into the VAT figures.
2. **Every tender records the rate it used.** Rates move — a sale settled last
   week keeps last week's rate, so historical totals never drift.
3. **Change is a negative tender, not a subtraction.** A customer paying USD and
   taking ZiG change moves both drawers; only a per-tender record shows that.

**Exchange rates** (`/api/currency/rates`) are append-only — a correction is a
new entry, never an edit — and quoted the way the street quotes them:
`units_per_base`, so 26 ZiG to the dollar is `26.0`. A currency with no rate on
record is refused rather than guessed at.

**Split tender.** A sale accepts a list of payments across methods *and*
currencies — part USD cash, part ZiG cash, part card — and each is converted at
the rate in force. Under-tendering is rejected with the shortfall named. Change
is returned in the currency most of the cash arrived in, or in
`change_currency` if the cashier chooses otherwise.

```jsonc
POST /api/pos/sales
{
  "items": [{"product_id": 1, "quantity": 2}],
  "tenders": [
    {"method": "cash", "currency_code": "USD", "amount": 5.00},
    {"method": "cash", "currency_code": "ZWG", "amount": 130.00},
    {"method": "card", "amount": 2.50, "reference": "AUTH77"}
  ],
  "change_currency": "ZWG"
}
```

The single-tender fields (`payment_method` / `amount_tendered`) still work
unchanged, so a single-currency installation never has to think about any of
this. `GET /api/currency` reports the trading currencies and live rates.

## Till hardware

| Device | Plug in and go? | How |
|---|---|---|
| **Barcode scanner** (USB or wireless) | **Yes** | Scanners emulate a keyboard: they type the code and press Enter. The Front Shop scan field listens for that and looks the code up against `barcode` then `nappi_code`. No driver, no configuration. |
| **Receipt / label printer** | Yes, two ways | Without the device agent, printing goes through the browser (`@page` sized 80mm for receipts, 70×40mm for labels) — install the printer in Windows and set it default; add Chrome's `--kiosk-printing` to skip the dialog. With the agent, raw ESC/POS is written straight to the port: silent, and it can kick the drawer. |
| **Cash drawer** | Needs the agent | Drawers open on an ESC/POS pulse sent through the printer's RJ11 port. A browser cannot send it. |
| **Card terminal** | Needs the agent + a driver | See below. |
| **Mobile money** (EcoCash, OneMoney) | Needs the agent + a driver | Push-and-poll, not a blocking call — see below. |

### Card payments

Card tender is captured on the sale either way — auth code, acquirer reference,
masked PAN, scheme, terminal ID and settlement batch — because without those a
card sale can be totalled but never matched to the bank.

- **Standalone machine (no integration):** the cashier keys the amount into the
  terminal and captures the slip detail in the payment panel.
- **Connected terminal:** the device agent pushes the amount to the machine and
  the approval comes back automatically. Adding an acquirer means writing one
  `TerminalDriver` class — see `device-agent/README.md`. A simulator driver ships
  by default so the whole flow works before any hardware or merchant agreement
  exists.

**Mobile money** settles as a `mobile_money` tender carrying the provider's
reference, so it reconciles the same way card does. The flow is asynchronous by
nature: the till pushes a request to the customer's handset and polls until they
approve, cancel, or the request expires — a dropped poll is treated as still
pending, so a flaky connection never loses a payment that went through. A
`PaynowDriver` skeleton is in place; the wire protocol needs their integration
guide.

**Card Reconciliation** (Retail → Reconciliation) imports the acquirer's
settlement CSV and matches it against the card takings on record. Column names
are matched loosely across acquirers. Lines match on auth code first, then
acquirer reference, then a same-day amount as a last resort — amount-only
matches are flagged `weak` rather than trusted. The report separates matched,
amount-mismatched, banked-but-never-rung-up, and rung-up-but-never-banked, with
the overall variance.

> Medical-aid claiming is still simulated (`services/claims_engine.py`). Going
> live means onboarding with a switch such as MediSwitch or Healthbridge; the
> claim flow, patient-liable split and reporting are already built around it.

## Data display

Lists are rendered by one component, `components/DataTable.tsx`, so display is
governed centrally rather than screen by screen:

- **Truncation** — columns declare `truncate: n`; longer values are clipped with
  an ellipsis and the full text stays available on hover. `<Truncate>` is also
  exported for use outside a table.
- **Pagination** — 25 rows per page by default, switchable to 10/25/50/100, with
  a range readout. Changing the filter set returns to page one.
- **Density** — compact / comfortable / spacious, toggled from the toolbar and
  remembered in `localStorage` across sessions.
- **Sorting** — per-column, numeric-aware, driven by an explicit `value()`
  accessor so a sortable column can render arbitrary markup.
- **Totals** — columns declare `total()`; the footer sums the filtered set.
- **Row → record** — `rowHref` makes every row open its own detail page.

`components/Filters.tsx` supplies the multi-dimensional filter bar: free-text
search, a date range, and any number of named dimension selects, all combinable,
with a Clear action that appears once a filter is active. `applyFilters()` runs
the same predicate set over any row type. `<EntityLink>` renders cross-record
hyperlinks and stops propagation so it works inside a clickable row.

### Record pages

Every list row opens a record: Patient, Product, Purchase order, Opportunity,
Account, Contact, Case. Each is a `Highlights` strip over tabbed detail, and
records hyperlink to each other — a case links to its customer, a purchase-order
line to the product, a contact to its account.

## Screen conventions

Every screen shows **one dataset at a time**. Where a module has several related
lists they become horizontal tabs rather than stacked tables — the only screen
that deliberately combines several sources is the Command Centre overview.

Tab state lives in the URL as `?tab=`, handled by `components/PageTabs.tsx`
(`usePageTabs` + `<PageTabs>`), so any view can be linked, bookmarked and
reloaded, and the browser back button steps through tabs. Tabs carry live record
counts. Row-level detail expands in place rather than opening a second table —
see Procurement, where a purchase order expands to show its lines.

| Screen | Tabs |
|---|---|
| Front Shop | Till · Awaiting payment |
| Dispensary | Prescription · Dangerous drugs · OTC, each with its own side rail (Repeats due · Recent scripts · Schedule rules, or Hand-over log · Schedule rules) |
| Inventory | Products · Batches & expiry · Movement history |
| Procurement | Purchase orders · Reorder needs |
| Accounts | Accounts · Contacts |
| Campaigns | New campaign · Campaign history |
| Opportunity record | Line items · Quotations · Activity |
| Revenue Intelligence | Forecast · Conversion · Rep performance · Attribution |
| Analytics | Daily totals · VAT/tax · Stock valuation · Patient tax statement |
| Patient record | Prescriptions · Dispensing history · Purchases · Tax statement |
| Control Panel | Price file import · Audit log · Backups · CRM automation · Templates |

## Feature map

| Area | What's included |
|---|---|
| **Dispensary** | Script capture, dosage/repeats/auto-refill per item, AI drug-interaction & allergy check, dispense → pending sale handed to POS, repeats-due worklist |
| **Three dispensing routes** | The dispensary is split by schedule policy (`backend/app/schedule_policy.py`). **Prescription (S3–S4)** — normal script flow, pharmacist only. **Dangerous drugs (S5–S6)** — a mandatory compliance checklist (patient identity verified with ID number recorded, original script sighted, prescriber verified, plus an independent witness for S6) is enforced server-side before any stock moves; S6 allows no repeats and S7/S8 are refused outright. **OTC / pharmacy medicine (S0–S2)** — pharmacist-initiated sales with indication, counselling confirmation and referral flag, kept in their own pharmacy-medicine register |
| **Schedule register** | Fully electronic S5/S6 register — every dispense/receipt/adjustment recorded immutably with patient, prescriber, balance and reference |
| **Point of Sale** | Barcode scanning (scan field + Enter), basket, cash/card/medical-aid tender, change calculation, loyalty earn & redeem, airtime sales, receipt, void with stock reversal |
| **Medical aid claiming** | Realtime claim simulation at checkout (approve/partial/reject with patient levy); swap `services/claims_engine.py` for a live switch |
| **Stock control** | Product catalogue (NAPPI/barcode/schedule), movements audit, receive/adjust/return, low-stock flags |
| **Batch & expiry (FEFO)** | Every receipt creates a batch with expiry; dispensing/sales consume First-Expiry-First-Out; expired stock blocked from sale; expiring-soon alerts (90 days); expired-batch write-offs; voids restore the exact batches drawn from |
| **Ordering** | Draft POs auto-generated per supplier from reorder levels, send → receive workflow updates stock and register |
| **Reminders** | APScheduler jobs: repeat-prescription reminders (incl. auto-refill wording), birthday messages, free-type SMS/email; console fallback when no SMTP/SMS gateway configured |
| **Label & receipt printing** | Dispensing labels (70×40mm) with patient, directions, auto-generated cautions, batch/expiry, schedule and repeats — printed automatically on dispense, reprintable from the patient record. Thermal 80mm tax-invoice receipts with VAT breakdown, tender, change, loyalty and claim outcome |
| **Cashier shifts** | Open a shift with a counted float, sales attributed automatically, end-of-shift cash-up showing expected vs counted with variance, plus card and medical-aid takings; full shift history |
| **Supplier price files** | CSV import matched on NAPPI → barcode → name, with a dry-run preview of every price change before applying; cost and selling prices toggled independently |
| **Audit log** | Every state-changing API call recorded with user, action, endpoint, result and IP — admin/pharmacist visible, filterable by user |
| **Backups** | Consistent online SQLite backups (nightly at 23:30, 20 most recent retained) plus on-demand backup and download |
| **Reports** | Dashboard KPIs, daily totals by payment method, VAT report, patient tax/medical-expense statement (SA tax year), dispensing history, stock valuation |
| **Leads console** | Three-pane sales console — saved list views with live counts, a dense record list with score rings and bulk reassignment, and a record preview pane. Leads are scored 0–100 and rated hot/warm/cold on capture; the preview shows a **full score breakdown** (`GET /api/crm/leads/{id}/score`) itemising every factor and its contribution, grouped by fit, contactability, value, engagement and automation. Includes a board view by stage, duplicate detection on email/phone/name, and one-click conversion into an account + contact + opportunity |
| **CRM — accounts & contacts** | Corporate accounts (clinics, old-age homes, employers, wholesale) with credit terms and owners; contacts with lifecycle stage, source and POPIA marketing consent; per-account overview rolling up deals, tickets, activities and revenue |
| **CRM — sales pipeline** | Drag-and-drop kanban across New → Qualified → Proposal → Negotiation → Won/Lost, auto-set probability, weighted forecast, win rate, close-lost reasons, and every stage change logged as an activity |
| **Opportunity workspace** | A record workspace rather than a form: chevron **Path** across the forward stages (closed-lost is an exit, not a step) that advances the deal on click, a highlights strip of value/weighted/close-date/quotes/stage, product line items (qty, unit price, per-line discount) rolling up to the deal value, versioned quotations with numbering, VAT split and validity dates, an activity composer, and a chronological timeline. The board view adds probability bars, deal age and a stale flag past 30 days |
| **CRM — automation** | Declarative rules evaluated server-side on lead creation, ticket creation and deal stage change: lead assignment and scoring, ticket routing by category, SLA escalation of breached tickets, and automatic task creation on entering a stage — each rule ordered, toggleable and counting its own fires, managed from Administration → CRM automation |
| **CRM — web-to-lead / web-to-case** | Unauthenticated `POST /api/public/web-to-lead` and `/web-to-case` endpoints so a website form feeds straight into the scored lead queue or the help desk, running the same assignment rules |
| **CRM — templates** | Reusable SMS and email templates by category (campaign, ticket reply, deal, general) with `{first_name}` / `{points}` / `{pharmacy}` merge fields |
| **Revenue Intelligence** | Purpose-built SVG charting (`components/charts.tsx`, no chart library): stacked six-month forecast columns with a dashed weighted-forecast marker and a scaled value axis, a tapered conversion funnel showing stage-to-stage drop-off, rep leaderboard bars comparing open pipeline against closed won, and a channel-attribution donut — each with a drill-down table beneath it |
| **CRM — activities & tasks** | Calls, meetings, tasks and notes against any account, contact, deal, ticket or patient, with due dates and a personal open-task list |
| **Marketing** | Eight live segments computed from real data (chronic, birthdays, loyalty, lapsed 90 days, repeats due, medical aid, private, all) — all consent-gated. Campaign composer with merge fields, AI copywriting, audience preview and per-recipient delivery tracking |
| **Help desk** | Tickets with category, priority-driven SLA targets (urgent 4h → low 72h), threaded customer/staff replies plus internal notes, auto-reopen on customer reply, CSAT rating, and stats for breaches, first-response and resolution times |
| **AI (Claude)** | Interaction checks, patient clinical summaries, counseling notes, natural-language business Q&A grounded in live data — plus CRM helpers: campaign copywriting, customer-service reply drafting and AI account reviews. Enable by setting `ANTHROPIC_API_KEY` in `backend/.env` |

## Configuration (`backend/.env`)

See `backend/.env.example`. Notable keys: `ANTHROPIC_API_KEY` (AI features),
`SMTP_*` (email), `SMS_GATEWAY_URL` (HTTP GET template with `{phone}` /
`{message}` placeholders), `VAT_RATE`, `PHARMACY_NAME`.
