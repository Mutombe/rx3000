# RX5000: Detailed Description of the System

**Draft specification for patent counsel.**
Figures are given as schematics for a draughtsman to redraw formally. Reference
numerals follow the convention *(FIG. n, item nn)*.

---

## Table of contents

1. Field and background
2. Overview of the system architecture (FIG. 1)
3. Data model (FIG. 2)
4. Tenant isolation
5. The dispensing subsystem (FIG. 3)
6. Directions shorthand and label generation (FIG. 4)
7. Clinical screening and acknowledgement
8. Benefit adjudication and shortfall settlement (FIG. 5)
9. Point-of-sale settlement and multi-currency tender
10. Delivery-agent custody accounting (FIG. 6)
11. Trust-gated metric publication (FIG. 7)
12. Regulatory document register (FIG. 8)
13. Statutory fiscalisation (FIG. 9)
14. Multi-branch consolidation and head-office control
15. Patient and prescriber portals
16. Verification harness (FIG. 10)
17. Worked end-to-end example
18. Glossary

---

## 1. Field and background

The invention relates to computer-implemented systems for operating a regulated
retail pharmacy.

A retail pharmacy is unusual among retail businesses in four respects, and the
combination is what makes conventional retail software inadequate:

**It dispenses against an instruction written by a third party.** The
prescription is authored by a prescriber, interpreted by a pharmacist, and
consumed by a patient. Three parties, three vocabularies, and the record must
satisfy all of them plus an inspector.

**It is paid by somebody other than the customer.** A medical-aid scheme meets
part of the price. The remainder, the *shortfall*, is settled by the patient
separately, and the two settlements happen at different moments, sometimes in
different places, and are adjudicated by a party outside the system.

**Its right to trade is conditional and expires.** Premises licences, controlled-
substance permits, fire certificates, tax clearances and municipal licences each
expire on their own cycle, from different authorities. The pharmacy may not
lawfully open without them and cannot demonstrate lawful past trading without
retaining the superseded ones.

**Its errors are clinical.** A quantity typed wrongly is not a pricing error.

The described embodiment is deployed in Zimbabwe. Its particular conditions
sharpen each of the four characteristics above: two currencies circulating at
one counter, a mandatory receipt fiscalisation regime, and medical-aid schemes
that routinely cover less than the charged price.

---

## 2. Overview of the system architecture

### FIG. 1: System architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│  CLIENTS (10)                                                            │
│                                                                          │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐         │
│  │ Dispensary │  │  Till /    │  │  Patient   │  │ Prescriber │         │
│  │  (11)      │  │  POS (12)  │  │ portal(13) │  │ portal(14) │         │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘         │
│        │  90 screens, 92 shared components (React/TypeScript)            │
└────────┼───────────────┼───────────────┼───────────────┼────────────────┘
         │               │               │               │
         └───────────────┴───────┬───────┴───────────────┘
                                 │  HTTPS, bearer token
┌────────────────────────────────▼────────────────────────────────────────┐
│  APPLICATION SERVER (20)  — FastAPI, 461 endpoints in 48 routers        │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ MIDDLEWARE STACK (21)                                             │   │
│  │  · tenant resolution (22)   · branch freeze (23)                  │   │
│  │  · audit capture (24)       · request size limit (25)             │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ DOMAIN SERVICES (30) — 76 modules                                 │   │
│  │                                                                    │   │
│  │  clinical (31)        money (32)          statutory (33)          │   │
│  │  · interactions       · pricing           · fiscal                │   │
│  │  · doses              · claims_engine     · compliance            │   │
│  │  · conditions         · currency          · era (remittance)      │   │
│  │  · refill_timing      · posting           · settlements           │   │
│  │  · sig (shorthand)    · driver_account                            │   │
│  │                                                                    │   │
│  │  insight (34)         control (35)                                │   │
│  │  · movement           · permissions                               │   │
│  │  · seasonality        · hq                                        │   │
│  │  · basket             · user_types                                │   │
│  │  · churn              · tenancy                                   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                          │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │ PERSISTENCE (40) — SQLAlchemy ORM, 92 entities                    │   │
│  │  TenantMixin applies a pharmacy filter to every ORM query (41)    │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │
                    ┌────────────▼────────────┐
                    │  DATABASE (50)          │
                    │  PostgreSQL (hosted) or │
                    │  SQLite (single till)   │
                    └─────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│  VERIFICATION HARNESS (60) — 101 executable checks, run outside the      │
│  request path, reading source and database. See FIG. 10.                 │
└─────────────────────────────────────────────────────────────────────────┘
```

The deployment target is deliberately dual: a single pharmacy may run the whole
stack on the till computer against SQLite, and a group runs it against hosted
PostgreSQL. This is why tenant isolation (§4) is enforced in the ORM session
rather than by database row-level security, which SQLite does not offer.

---

## 3. Data model

### FIG. 2: Core entities and the relationships that matter

```
                          ┌───────────┐
                          │ Pharmacy  │ (100)  tenant root
                          └─────┬─────┘
                                │
              ┌─────────────────┼──────────────────┐
              │                 │                  │
        ┌─────▼─────┐    ┌──────▼──────┐   ┌───────▼──────┐
        │  Branch   │    │   Patient   │   │     User     │
        │  (101)    │    │   (102)     │   │    (103)     │
        │ · frozen  │    │ · portal    │   │ · user_type  │
        │ · lat/lng │    │   code      │   │ · till pin   │
        └─────┬─────┘    └──────┬──────┘   └──────────────┘
              │                 │
              │          ┌──────▼────────────┐        ┌──────────┐
              │          │  Prescription     │◄───────│  Doctor  │
              │          │  (104)            │        │  (105)   │
              │          │  · rx_number      │        └──────────┘
              │          │  · draft_ref      │
              │          │  · status         │
              │          └──────┬────────────┘
              │                 │ 1..n
              │          ┌──────▼──────────────┐      ┌───────────────┐
              │          │ PrescriptionItem    │      │ ScriptChange  │
              │          │ (106)               │◄─────│ (107)         │
              │          │ · repeats_allowed   │      │ append-only   │
              │          │ · repeats_used      │      │ field/old/new │
              │          │ · dosage_instr.     │      │ /reason/who   │
              │          └──────┬──────────────┘      └───────────────┘
              │                 │ 1..n
              │          ┌──────▼──────────┐
              │          │  Dispensing     │ (108)
              │          │  · is_repeat    │
              │          │  · pharmacist   │
              │          └──────┬──────────┘
              │                 │
        ┌─────▼─────────────────▼────────┐      ┌──────────────┐
        │           Sale (109)           │◄─────│ Claim (110)  │
        │  · status  pending|part_paid|  │      │ · approved   │
        │            paid                │      │ · patient_   │
        │  · branch_id ◄── attribution   │      │   liable     │
        └───┬────────────────────┬───────┘      └──────────────┘
            │ 1..n               │ 1..n
    ┌───────▼────────┐   ┌───────▼─────────┐    ┌────────────────┐
    │ SaleItem (111) │   │ SaleTender(112) │    │ FiscalReceipt  │
    │ · quantity_    │   │ · method        │    │ (114)          │
    │   returned     │   │ · currency      │    │ · prev_hash    │
    └────────────────┘   │ · rate_used     │    │ · receipt_hash │
                         │ · amount_in_base│    └────────┬───────┘
                         └─────────────────┘             │
            ┌────────────────────────────────┐   ┌───────▼──────┐
            │  Waybill (113)                 │   │ FiscalDay    │
            │  · driver_profile_id           │   │ (115)        │
            │  · cod_amount / cod_collected  │   └──────────────┘
            │  · cod_settled_at / shift_id   │
            └────────────┬───────────────────┘
                         │
                 ┌───────▼────────┐    ┌───────────────────────┐
                 │  Driver (116)  │    │ ComplianceDocument    │
                 │  · cod_limit   │    │ (117)                 │
                 │  · licence exp │    │ · kind / expires_on   │
                 └────────────────┘    │ · superseded_by_id    │
                                       │ · file_data (base64)  │
                                       └───────────────────────┘
```

**Attribution note (item 109).** A `Sale` carries `branch_id`; a `Prescription`
does **not**. A prescription is authored by a prescriber and captured by a
pharmacy. It is not held at a shop. Consequently any per-branch analysis of
dispensing activity must reach the branch through the sale
(`Dispensing → Sale → branch_id`), and dispensings with no sale cannot be
attributed to any branch at all. This is not a modelling deficiency but a
factual one, and §11 describes how the system reports it rather than concealing
it.

---

## 4. Tenant isolation

Every entity that belongs to one pharmacy carries `TenantMixin`. A SQLAlchemy
session event applies a `pharmacy_id` predicate to every ORM query issued on a
stamped session, before it reaches the database. The current pharmacy is held in
a `contextvar` set by middleware from the authenticated principal.

The design constraint is stated in the source: there are ninety-two tables and
several hundred queries; a missed predicate leaks a patient list rather than
raising an error, and nothing about the leaking code looks different from the
correct code. A rule enforced by remembering is not enforced. The failure mode of
a query written by somebody who has never read the tenancy module is that it
returns their own pharmacy's rows.

Two deliberate exclusions:

- **Raw SQL is not filtered.** The ORM cannot see inside a string. A separate
  verification check asserts that no raw SQL touches a tenant-scoped table.
- **Shared reference data is not scoped**: diagnosis codes, jurisdiction fee
  models. Those are the same book for everyone.

An explicit `unscoped()` context manager exists for the small number of
operations that legitimately cross tenants (platform administration, and the
patient-portal entry point, which must resolve a patient *before* it knows which
pharmacy the request belongs to).

---

## 5. The dispensing subsystem

### FIG. 3: Dispensing flow and its three settlement routes

```
      ┌────────────────────────────────────────────────────────────┐
      │  STEP TRAIL (200) — derived, never stored                   │
      │  ① Patient & prescriber  ② Script items  ③ Compliance      │
      │  ④ Safety check & dispense                                 │
      │  Each state computed from the SAME predicates that gate     │
      │  the commit control (207), so it cannot contradict it.      │
      └────────────────────────────────────────────────────────────┘

   ┌──────────────┐   ┌──────────────┐   ┌──────────────────────────┐
   │ ① Patient    │   │ ② Items      │   │ ③ Compliance (controlled │
   │   + funder   │──▶│   + directions│──▶│    substances only)     │
   │   standing   │   │   (FIG. 4)   │   │                          │
   │   + repeats  │   │   + margin    │   └──────────┬───────────────┘
   │     due (201)│   │     tag (202) │              │
   └──────────────┘   └──────────────┘              │
                                                     ▼
                        ┌────────────────────────────────────────┐
                        │ ④ Screening (203)  — dose maxima,      │
                        │    conditions, refill timing.          │
                        │    Non-blocking; named acknowledgement │
                        │    required. Coverage disclosed.       │
                        └──────────────┬─────────────────────────┘
                                       ▼
                        ┌────────────────────────────────────────┐
                        │ SPLIT DISPLAY (204)                     │
                        │   Scheme pays  ……  X                    │
                        │   SHORTFALL    ……  Y   ◄ quoted from    │
                        │                        the same rule    │
                        │                        that will charge │
                        │                        it (FIG. 5)      │
                        └──────────────┬─────────────────────────┘
                                       ▼
              ┌────────────────────────┼────────────────────────┐
              ▼                        ▼                        ▼
   ┌──────────────────┐   ┌────────────────────┐   ┌──────────────────────┐
   │ (205) SEND TO    │   │ (206) TAKE PAYMENT │   │ (207) OUT FOR        │
   │       TILL       │   │       NOW          │   │       DELIVERY       │
   │                  │   │                    │   │                      │
   │ Sale → pending   │   │ Tenders collected  │   │ Waybill raised,      │
   │ Patient walks to │   │ here for Y only,   │   │ agent assigned,      │
   │ the front shop   │   │ never the gross    │   │ COD = Y + fee        │
   │                  │   │                    │   │ Sale stays unsettled │
   └──────────────────┘   └────────────────────┘   │ (FIG. 6)             │
                                                    └──────────────────────┘
```

**Item 200, the step trail.** Displays where the dispense stands and what the
current step is waiting for, in a sentence naming the missing thing. It gates
nothing and moves focus only on an explicit click. Its states derive on every
render from the same expressions that disable the commit control, so a display
saying "done" beside a disabled button is structurally impossible.

**Item 201, repeats due.** When a patient is identified, the screen lists that
patient's repeats that are due or overdue, with their value, and offers to add
them to the script in progress. Every other repeat screen in the system reports
a loss after it has occurred; this is the only place one can still be prevented,
and it costs nothing because the patient is present and the script already
exists.

**Item 202, per-line margin.** Each line displays its own gross margin, banded
into four states that say what to do rather than what the number is: below cost
(the only band that shouts), thin (a discount here comes out of the pharmacy),
ordinary, room to negotiate. The same figure appears on search results *before*
a medicine is added, because that is where a substitution between a brand and
its generic is actually decided. Where no cost is on file the badge is withheld
entirely. Not knowing is not a margin of one hundred per cent, and the
difference matters when the figure is about to justify a discount.

---

## 6. Directions shorthand and label generation

### FIG. 4: Expansion pipeline

```
  DISPENSER TYPES              EXPANSION (300)                    LABEL (310)
  ┌───────────────┐    ┌──────────────────────────┐    ┌────────────────────┐
  │  1t tds pc    │───▶│ tokenise on whitespace   │───▶│ Take ONE tablet    │
  └───────────────┘    │        │                  │    │ three times a day  │
                       │        ▼                  │    │ after food.        │
                       │ per-token dictionary      │    └────────────────────┘
                       │ lookup (301)              │
                       │  · hit  → expansion       │      ┌──────────────────┐
                       │  · miss → PASS THROUGH    │◄─────│ unknown token is │
                       │           UNCHANGED (302) │      │ ordinary English │
                       │        │                  │      │ and is valid     │
                       │        ▼                  │      └──────────────────┘
                       │ numeral–noun agreement    │
                       │ (303)                     │
                       │  "TWO tablet" → "tablets" │
                       │        │                  │
                       │        ▼                  │
                       │ sentence case + full stop │
                       └──────────────────────────┘

  LIVE PREVIEW (304)  — the identical rule, mirrored client-side, rendering
  the sentence beneath the field while the shorthand is still being typed.
  The field itself is never rewritten under the cursor.

  UNRECOGNISED TOKENS (305) are named beneath the preview — not as an error,
  because ordinary English is a valid direction, but so that `stst` is
  visibly not `stat`.
```

**The dictionary (item 301).** 75 codes across five categories (quantity,
frequency, timing, route, form) stored per tenant so a pharmacy may add its own
inherited shorthand without waiting for a release. Eight codes carry a *caution*
string naming how else they can be read.

**The collision (item 306).** `od` is *omni die* (once a day) in Southern African
dispensing practice and *oculus dexter* (right eye) in ophthalmology. An earlier
implementation dodged this by seeding codes `od_eye` and `os_eye`; no dispenser
has ever typed an underscore into a directions field at speed, so the collision
was not resolved but concealed behind codes that could never fire. The system now
takes `od` as once-a-day, offers **no Latin laterality code at all**, and accepts
`r-eye`, `l-eye`, `b-eye`, `r-ear`, `l-ear`, `b-ear`, which cannot be read two
ways and expand to the words written in full.

Similarly `iv` is deliberately absent as a roman numeral: four is written `4`,
because `iv` is intravenous and the two cannot share a field.

**The generated inspection sheet (item 307).** The dictionary renders to a
printable document for a regulatory inspection, generated from the live
dictionary at request time. It opens with the statement an inspection is actually
asking for, that no code reaches a label, and lists every code with what it
prints, its origin, and a "read it twice" column for the ambiguous ones. A
printed copy cannot disagree with the dispensary.

---

## 7. Clinical screening and acknowledgement

Four independent screening services run as the basket changes, not on a button:

| Service | Reads | Produces |
|---|---|---|
| `interactions` | script lines + six months of dispensing history | pairwise findings with effect and action |
| `doses` | typed directions parsed to quantity × frequency | over-maximum, unreadable, or not-judged |
| `conditions` | patient's recorded conditions × line ingredients | 113 condition–ingredient pairs, 11 conditions |
| `refill_timing` | last supply date, days of supply | early-refill severity; `stop` at schedule 5+ |

Three properties are common to all four and are the substance of §9 of the
summary:

1. **A clear result never says "safe".** It says none of the pairs this system
   holds was found, which is a different and true sentence.
2. **Coverage is disclosed on every result**, cleared or not, naming the
   medicines for which nothing is held.
3. **A major finding requires named acknowledgement**, which is stored against
   the script. Adding or removing a line invalidates a prior acknowledgement,
   because the basket is now a different question.

---

## 8. Benefit adjudication and shortfall settlement

### FIG. 5: One rule, two invocations, verified to agree

```
  ┌─────────────────────────────────────────────────────────────────┐
  │              COVER RULE (400) — single implementation            │
  │                                                                  │
  │   _apply_rule(lines) → (claimable_total, approved)               │
  │     medicine lines      × MEDICINE_COVER                         │
  │     front-shop lines    × FRONT_SHOP_COVER                       │
  └───────────┬──────────────────────────────────┬──────────────────┘
              │                                  │
   PROSPECTIVE│ (401)                RETROSPECTIVE│ (402)
   basket not │                       sale exists │
   yet a sale │                                   │
              ▼                                   ▼
  ┌───────────────────────────┐      ┌────────────────────────────┐
  │ estimate(patient, lines)  │      │ _adjudicate(claim, sale)   │
  │ priced at SHELF price —   │      │ over sale.items            │
  │ the basis the sale will   │      │                            │
  │ be billed on              │      │ patient_liable =           │
  │                           │      │   sale.total − approved    │
  │ → scheme_pays, shortfall  │      │ → claim record             │
  └───────────┬───────────────┘      └────────────┬───────────────┘
              │                                   │
              ▼                                   ▼
     quoted at the dispensary            charged at the till
              │                                   │
              └──────────────┬────────────────────┘
                             ▼
              ┌──────────────────────────────────┐
              │ PARITY CHECK (403)               │
              │ qa/shortfall-split.py            │
              │  · builds a basket               │
              │  · quotes it                     │
              │  · materialises it as a sale     │
              │  · adjudicates it                │
              │  · FAILS if the two differ       │
              │  · also asserts approved +       │
              │    liable = total (nothing       │
              │    billed twice or lost)         │
              └──────────────────────────────────┘
```

**The rejected alternative (item 404).** The system already contained
`pricing.price_basket`, computing a `patient_portion` from levy plus
maximum-medical-aid-price excess. That service models the scheme's *regulated*
price: fee model, professional fee, levy, MMAP cap. The sale a claim is raised
against is billed at *shelf* price. Two coherent calculations of two different
things; quoting one as the other is arithmetic on mismatched data, wrong by a
plausible-looking margin on every scheme line. This is recorded here because a
patent examiner assessing obviousness should see that the obvious source was
available, was tried, and was wrong.

**Terminology (item 405).** The amount is named *shortfall*, the trade's own
word, wherever a scheme was billed, and *patient pays* where none was, because a
private patient paying cash is paying the price and not a shortfall. Its
components keep their own names (*levy*, the scheme's co-payment, a term of the
member's cover; *above scheme rate*, a consequence of what was dispensed),
because a patient querying the amount is querying one and not the other.

---

## 9. Point-of-sale settlement and multi-currency tender

The counter takes United States dollars and Zimbabwe gold simultaneously, across
cash, card, and several mobile-money wallets. A tender is recorded as a row
carrying: method, currency code, amount as handed over, the rate in force at that
moment, the amount converted to base, and the *instrument*, which wallet, which
bank, as a column rather than as text at the front of a reference for a screen
to parse back out.

Change is written back as a **negative tender** in whichever currency it was
given, so a drawer counted at five o'clock can be matched to the day's tenders
rather than to a column of sales that each said "cash".

`paid_on(sale_ids)` sums the tenders. Sale status is derived from that sum
against the total; there is no second column holding the same fact.

---

## 10. Delivery-agent custody accounting

### FIG. 6: Value custody state machine

```
   DISPENSARY                    ROAD                        TILL
   ──────────                    ────                        ────

   ┌─────────────┐
   │ Sale raised │  status: pending
   │ (500)       │  agent account: —
   └──────┬──────┘
          │ waybill raised, agent assigned,
          │ COD = shortfall + delivery fee (501)
          │ ┌──────────────────────────────────────┐
          │ │ DISPATCH GATE (502)                   │
          │ │  refused if agent licence expired     │
          │ │  refused if agent holding > cod_limit │
          │ └──────────────────────────────────────┘
          ▼
   ┌──────────────────────────────┐
   │ OUT (503)                     │  status: pending
   │  agent "to collect": +COD     │  ┌─────────────────────────────┐
   │  owed by NOBODY — the         │  │ TILL SUPPRESSION (504)       │
   │  medicine has not changed     │  │ Cash / Card / Mobile buttons │
   │  hands                        │  │ are ABSENT for this sale.    │
   └──────┬───────────────────────┘  │ Row reads "on <agent>'s      │
          │ collected at the door     │ account".                    │
          ▼                           └─────────────────────────────┘
   ┌──────────────────────────────┐
   │ HOLDING (505)                 │  status: STILL pending
   │  agent "holding": +collected  │  a motorbike is not a till
   │  a DEBT the agent owes        │
   └──────┬───────────────────────┘
          │ hand-in to an OPEN shift (506)
          ▼
   ┌───────────────────────────────────────────────────────────┐
   │ SETTLED (507)                                              │
   │  · tender written against the sale through the IDENTICAL   │
   │    primitive the counter uses (508)                        │
   │  · sale → paid | part_paid on the same rule                │
   │  · agent balance clear                                     │
   │  · counted, not assumed: a short hand-in is recorded as a  │
   │    short hand-in, with the variance kept (509)             │
   │  · overpayment REFUSED, not trimmed — an agent taking more │
   │    than the sale is owed is a mistake or a second          │
   │    transaction, and both need a person (510)               │
   └───────────────────────────────────────────────────────────┘
```

**The two figures are never summed (items 503, 505).** *Holding* is money the
shop owns and does not have. *To collect* is money nobody owes yet. Their sum is
a quantity with no referent, and it is precisely the quantity that would
otherwise be entered into a cash reconciliation.

**What the hand-in reports.** Which sales it closed, by number and amount, and
any collection that would not fit its sale, named rather than swallowed, because
somebody has that money and the books do not agree about it.

---

## 11. Trust-gated metric publication

### FIG. 7: Refusal path

```
   ┌────────────┐   ┌────────────┐
   │ Data set A │   │ Data set B │      e.g. repeat lines  /  visit totals
   └─────┬──────┘   └─────┬──────┘           dispensings   /  sale lines
         └────────┬───────┘
                  ▼
        ┌────────────────────────┐
        │ SEMANTIC INVARIANT     │  (600)
        │ evaluated at READ time │
        └───────┬────────┬───────┘
         holds  │        │  fails
                ▼        ▼
   ┌──────────────┐   ┌──────────────────────────────────────┐
   │ metric (601) │   │ REFUSAL OBJECT (602)                 │
   │ { value: …,  │   │ { untrustworthy: true,               │
   │   untrust-   │   │   matched: n, unmatched: m,          │
   │   worthy:    │   │   headline: "Basket value cannot be  │
   │   false }    │   │     measured on this data yet. The   │
   └──────┬───────┘   │     visits found are worth less than │
          │           │     the repeats they are supposed to │
          │           │     contain, which means the         │
          │           │     dispensings and the sales were   │
          │           │     never linked." }                 │
          │           └──────────────┬───────────────────────┘
          ▼                          ▼
   ┌──────────────┐        ┌──────────────────────────┐
   │ figure shown │        │ EXPLANATION shown WHERE   │
   │              │        │ THE FIGURE WOULD HAVE BEEN│
   └──────────────┘        └──────────────────────────┘
```

**A related but distinct case, partial attribution (item 603).** Where a metric
*can* be computed but is knowably incomplete, the system computes it and states
the size of the gap rather than refusing. In the described deployment, 2,510 of
2,537 dispensings in a ninety-day window carry no sale, so they cannot be
attributed to a branch. Per-branch movement figures are therefore drawn from the
2% that reached a till and **do not sum to the group total**. The response
carries the count, the share, and a sentence stating that the branches do not sum
to the group and why, rendered *above* the table, because a reader who has
already compared two branches will not revise a conclusion for a footnote.

---

## 12. Regulatory document register

### FIG. 8: Expected set, held set, and the verdict

```
   EXPECTED SET (700) — declared per jurisdiction
   ┌──────────────────────────────────────────────────────────────┐
   │ kind              issuer            renew   critical  why    │
   │ mcaz_premises     MCAZ              12 mo   YES       …      │
   │ mcaz_controlled   MCAZ              12 mo   YES       …      │
   │ tax_clearance     ZIMRA             12 mo   YES       …      │
   │ fire_certificate  Fire Brigade      12 mo   YES       …      │
   │ city_licence      City of Harare    12 mo   YES       …      │
   │ … 13 kinds in total                                          │
   └───────────────────────┬──────────────────────────────────────┘
                           │  outer join
   HELD SET (701)          ▼
   ┌──────────────────────────────────────────────────────────────┐
   │ ComplianceDocument rows for this branch, latest expiry wins   │
   └───────────────────────┬──────────────────────────────────────┘
                           ▼
   PER-KIND STATE (702)
   ┌───────────┬───────────┬──────────┬───────────┬─────────┬──────────┐
   │  expired  │  missing  │  urgent  │ expiring  │ undated │  valid   │
   │  (held,   │  (NEVER   │ (≤21 d)  │ (≤60 d)   │         │          │
   │   lapsed) │  recorded)│          │           │         │          │
   └─────┬─────┴─────┬─────┴──────────┴───────────┴─────────┴──────────┘
         │           │
         ▼           ▼
   ┌──────────────────────────────────────────────────────────────┐
   │ BRANCH VERDICT (703)                                          │
   │   any critical EXPIRED  → "cannot trade"                      │
   │   any critical MISSING  → "cannot be proved"                  │
   │   otherwise             → "renewals due" | "in order"         │
   └──────────────────────────────────────────────────────────────┘

   SUPERSESSION CHAIN (704) — append-only, walkable both ways
   ┌────────────┐    ┌────────────┐    ┌────────────┐
   │ MCAZ/2024  │───▶│ MCAZ/2025  │───▶│ MCAZ/2026  │ ◄ current
   │ expired    │    │ expired    │    │ expiring   │
   └────────────┘    └────────────┘    └────────────┘
        ▲                                     │
        └── from a lapsed number an inspector ─┘
            reads out, reach the current one
```

The distinction at item 703 is the substance. A document repository can report
what has been uploaded. Only a register defined against an expected set can
report what has not, and the difference between "we held it and it lapsed" and
"we have never recorded it" is the difference between a shop that must close
today and a shop that must find a filing cabinet.

**Verdict presentation (item 705).** Each branch's verdict appears on its row in
the branch table, linked to the register that explains it. The column is fetched
once for all branches rather than per row. It remains blank while loading rather
than showing a neutral dash: on a compliance column, "not known yet" and "nothing
wrong" must not look the same.

---

## 13. Statutory fiscalisation

### FIG. 9: Receipt chain and day close

```
   FISCAL DAY (800)  opened → receipts → closed → Z-report filed

   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
   │ Receipt 1│──▶│ Receipt 2│──▶│ Receipt 3│──▶│ Receipt n│
   │ prev: ∅  │   │ prev: h1 │   │ prev: h2 │   │ prev:h(n-1)│
   │ hash: h1 │   │ hash: h2 │   │ hash: h3 │   │ hash: hn │
   └──────────┘   └──────────┘   └──────────┘   └──────────┘
        │  two counters per receipt:
        │    receipt_counter — resets each fiscal day
        │    global_counter  — never resets
        ▼
   ┌──────────────────────────────────────────────────────────┐
   │ VERIFICATION (801)                                        │
   │  whole register  → walks every receipt                    │
   │  sampled         → takes the MOST RECENT n and returns    │
   │                    partial: true                          │
   │  per fiscal day  → localises a break to a day (802)       │
   └──────────────────────────────────────────────────────────┘

   ┌──────────────────────────────────────────────────────────┐
   │ Z-REPORT (803) — computed from receipts at READ time      │
   │  · by currency  (USD and ZiG in one day)                  │
   │  · by tax treatment — receipts carrying no VAT are        │
   │    "no VAT charged", NOT zero-rated and NOT exempt (804)  │
   │  · unfiled receipts named FIRST: a day closed with        │
   │    receipts queued or refused is filed short, and the     │
   │    totals look complete because they count every receipt  │
   │    written, filed or not (805)                            │
   └──────────────────────────────────────────────────────────┘
```

**Item 804 is a deliberate refusal to guess.** Zero-rated and exempt supplies are
treated differently in a value-added-tax return. Nothing on a receipt
distinguishes them. Choosing one would place a guess inside a statutory filing,
so the report states only what it knows.

**Corrections are credit notes, never voids.** A receipt filed with the authority
stays filed; a correction is a second document pointing at the first.

---

## 14. Multi-branch consolidation and head-office control

- **Branch freeze.** A head office may halt all writing operations at a branch.
  Reads and a defined always-allowed set continue; writes return HTTP 423 Locked
  with the reason. Enforced in middleware, not per endpoint.
- **Multidimensional permissions.** A grant is one capability, optionally on one
  branch, optionally bounded by value, daily value, hours of day, days of week,
  and whether it escalates or requires dual approval. Denials beat grants; an
  unknown capability fails closed.
- **Impersonation.** An administrator may act as another user for a bounded
  period. The session token carries `imp` and `imp_name` claims and every audit
  row records both the acting principal and the impersonated one.
- **Estate map.** Branches are placed by latitude and longitude with daily
  takings, so an estate is read geographically rather than as a list.

---

## 15. Patient and prescriber portals

Served as routes within the same client application, reached by a signed link.

- **Patient portal.** Four-digit code authentication with constant-time
  comparison, five attempts, fifteen-minute lockout. Shows prescription history,
  repeats and their next dates, and collection status. Designed at phone scale —
  16px base, 54px controls, no fetched font, because it is read on a phone, on a
  slow connection, by somebody who has never seen the software.
- **Share flow.** A staff member shares the link by WhatsApp, SMS or email, with
  the four-digit code deliberately **off** by default: a link and its code in one
  message means one forwarded message opens the record, which is the thing the
  code exists to prevent.
- **Prescriber portal.** A practice may send a prescription directly. The
  pharmacist reviews every script before dispensing and may substitute a product
  they stock.

---

## 16. Verification harness

### FIG. 10: What the harness reads and what it catches

```
  ┌────────────────┐   ┌────────────────┐   ┌────────────────┐
  │ CLIENT SOURCE  │   │ SERVER SOURCE  │   │  STYLESHEETS   │
  │ 90 screens     │   │ 461 endpoints  │   │  ~950 classes  │
  └───────┬────────┘   └───────┬────────┘   └───────┬────────┘
          └────────────┬───────┴────────────────────┘
                       ▼
        ┌───────────────────────────────────────────────┐
        │  101 CHECKS (900), each verified BOTH ways:    │
        │   · must fire on the broken code               │
        │   · must stay silent on the fixed code         │
        └───────────────────────────────────────────────┘
                       │
   ┌───────────────────┼────────────────────┬──────────────────┐
   ▼                   ▼                    ▼                  ▼
┌────────────┐  ┌──────────────┐  ┌─────────────────┐  ┌──────────────┐
│ response-  │  │ dead-classes │  │ authed-links    │  │ inherited-   │
│ shape (901)│  │ (902)        │  │ (903)           │  │ colour (904) │
│            │  │              │  │                 │  │              │
│ client     │  │ class named  │  │ <a href> at an  │  │ component    │
│ asserts    │  │ by markup,   │  │ authenticated   │  │ styles an    │
│ T[]; does  │  │ defined      │  │ API path — a    │  │ element the  │
│ the handler│  │ NOWHERE      │  │ navigation      │  │ global sheet │
│ return T[]?│  │ (34 found)   │  │ carries no      │  │ also paints  │
│            │  │              │  │ token           │  │              │
└────────────┘  └──────────────┘  └─────────────────┘  └──────────────┘

┌──────────────┐  ┌─────────────────┐  ┌──────────────────────────────┐
│ route-       │  │ branch-filters  │  │ shortfall-split, driver-      │
│ shadowing    │  │ (906)           │  │ account, sig-codes … (907)    │
│ (905)        │  │                 │  │                               │
│ /x/table     │  │ EXECUTES every  │  │ domain invariants exercised   │
│ registered   │  │ per-branch call │  │ against real data in a rolled │
│ after /x/{id}│  │ — an attribute  │  │ back transaction              │
│ answers 422  │  │ that does not   │  │                               │
│              │  │ exist is only   │  │                               │
│              │  │ found by running│  │                               │
└──────────────┘  └─────────────────┘  └──────────────────────────────┘
```

**Item 906 illustrates the class.** A per-branch analysis filtered on
`Prescription.branch_id`, a column that does not exist. Python does not check an
attribute until the line runs; SQLAlchemy does not check a column until the query
is built; and the line runs only when somebody narrows to one branch. Two
services carried it and both were dead from the day they were written, while the
group view beside them worked perfectly. In the browser the resulting unhandled
exception returned a response the CORS middleware never decorated, so the fault
was reported as a cross-origin failure: the wrong cause, on a different layer,
in a different subsystem.

---

## 17. Worked end-to-end example

A patient on a medical-aid scheme presents a repeat prescription and asks for it
to be delivered.

1. **Identification.** The dispenser finds the patient. The screen shows the
   scheme's standing and four repeats due, worth 1,284 in total, four already
   overdue. The dispenser adds two of them to the script.
2. **Directions.** For each line the dispenser types `1t bd pc`. The preview
   beneath the field reads *Take ONE tablet twice a day after food.* before the
   field is left.
3. **Margin.** Each line carries a margin badge. One reads 7% in amber, meaning thin,
   so a discount there would come out of the pharmacy.
4. **Screening.** The dose checker reports one line for which no maximum is held,
   naming it. No acknowledgement is required.
5. **Split.** The screen states: *Scheme pays 652.00 · Shortfall 1.00 to collect
   at the till*, quoted from the rule that will adjudicate the claim.
6. **Route.** The dispenser chooses *Out for delivery*, selects an agent whose
   entry reads "holding 40.00", enters a 3.00 fee and the address. The screen
   states: *The driver collects 4.00 (1.00 for the medicine + 3.00 delivery) at
   the door. It sits on their account until they hand it in, and the sale is
   settled then, not now.*
7. **Dispense.** Stock moves, the register entry is written, the claim is raised
   against the scheme, labels print with the expanded directions, a fiscal
   receipt is chained, a waybill is raised and the agent is dispatched.
8. **At the till.** The sale appears in *Awaiting payment* marked *out with
   \<agent\> · WB-0043*, with **no** Cash, Card or Mobile control.
9. **At the door.** The agent collects 4.00. The agent's account moves 4.00 from
   *to collect* to *holding*. The sale is still unsettled.
10. **Hand-in.** The agent hands in to an open shift. A tender of 4.00 is written
    against the sale through the counter's own primitive; the sale becomes paid;
    the agent's balance clears; the hand-in is recorded with its variance and the
    sale it closed.

---

## 18. Glossary

| Term | Meaning in this specification |
|---|---|
| **Shortfall** | The part of a charged price a medical-aid scheme did not cover, settled by the patient. Distinguished from *patient pays*, used where no scheme was billed. |
| **Levy** | A scheme's own co-payment, fixed or proportional; a term of the member's cover. |
| **Above scheme rate** | The excess over a reference (maximum medical aid) price; a consequence of what was dispensed. |
| **N-Repeat** | A repeat with N collections still to come. A 3-Repeat has three authorised supplies outstanding. Distinct from a *draft*. |
| **Draft** | A script captured but not finished, holding no register number. |
| **Waybill** | A delivery note carrying the consignment, the agent, and the amount to collect. |
| **Holding** | Value an agent has collected and not handed in; a debt owed to the pharmacy. |
| **To collect** | Value on the road, owed by nobody, the medicine not yet handed over. |
| **Fiscal day** | The statutory trading period opened and closed on the fiscal register, producing a Z-report. |
| **Critical document** | A regulatory document without which trading is unlawful. |
| **Cannot trade** | Verdict where a critical document is held and expired. |
| **Cannot be proved** | Verdict where a critical document has never been recorded. |
