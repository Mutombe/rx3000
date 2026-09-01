# RX5000 — Technical Summary of Inventions

**Applicant working title:** RX5000 Pharmacy Management System
**Field:** Computer-implemented systems for regulated retail pharmacy operations,
clinical dispensing safety, third-party benefit adjudication, and statutory
compliance evidencing.
**Date of this summary:** 1 September 2026
**Status:** Draft for patent counsel. Not a legal opinion.

---

## 0. How to read this document

This summary identifies **ten candidate inventions** embodied in a working
system. For each it states the problem, the conventional approach, what this
system does instead, and why the difference is technical rather than
presentational.

Section 11 is a candid assessment of which candidates are likely to survive a
prior-art search and which are not. Counsel should read Section 11 before
drafting: several items here are engineering quality rather than patentable
novelty, and filing broad claims over them invites rejection and wastes the
examination. The candidates are ranked so that the strongest can be claimed
independently and the weaker ones used as dependent claims that narrow the
strong ones.

---

## 1. The system in one paragraph

RX5000 is a multi-tenant pharmacy management system comprising a Python/FastAPI
application server (92 relational entities, 76 domain services, 461 HTTP
endpoints), a TypeScript/React single-page client (90 screens, 92 shared
components), and an executable verification harness (101 automated checks). It
manages the complete retail-pharmacy transaction: prescription capture,
clinical screening, dispensing, third-party benefit adjudication, point-of-sale
settlement, delivery-agent custody, stock and expiry control, statutory
fiscalisation, regulatory document evidencing, and multi-branch consolidation.

It is deployed against a jurisdiction (Zimbabwe) with three characteristics that
shape the inventions: a multi-currency counter (USD and ZiG simultaneously), a
mandatory receipt-fiscalisation regime, and third-party medical-aid schemes that
routinely cover less than the full price — producing a *shortfall* that the
patient settles separately.

---

## 2. Invention A — Trust-gated metric publication

*Refusing to publish a derived figure when its inputs cannot support it.*

**Problem.** A management report computes a figure from two or more independently
maintained data sets. When those sets disagree — because of an import defect, an
unlinked record, or a partial migration — the arithmetic still succeeds. The
report publishes a number that is internally consistent and factually false. In
this system's own history, a stock-movement report costed dispensings that had
never reached a sale at their average cost with zero revenue against them, and
reported a 1.9 million currency-unit loss for a profitable estate.

**Conventional approach.** Validate on ingest, or annotate the output with a
data-quality score. Both fail at the moment of use: ingest validation cannot
anticipate every downstream combination, and a quality score beside a number is
read as a caveat on a number rather than as a reason to disbelieve it.

**What this system does.** Each derived-metric service evaluates a *semantic
invariant* between its input sets before computing. Where the invariant fails,
the service returns a structured refusal object — carrying `untrustworthy:
true`, the diagnostic counts that establish the failure, and a natural-language
explanation of what is wrong with the data — **in place of the metric**. The
presentation layer renders the explanation where the figure would have been.

Three worked instances in the system:

| Metric | Invariant | On failure |
|---|---|---|
| Repeat basket value | Matched visit totals must be ≥ the repeat lines they are supposed to contain | Refuses; reports matched/unmatched counts |
| Stock movement profitability | Money may derive only from lines carrying a recorded sale price | Counts units, refuses to price them, states how many rows are affected |
| Branch compliance standing | An expected document is *expired* or *never recorded* — different verdicts | "Cannot trade" vs "cannot be proved" |

**Why technical.** The invariant is not a schema constraint (both data sets are
individually valid) and not a threshold alarm (the figure is not out of range —
it is meaningless). It is a cross-source semantic precondition evaluated at read
time, and the substitution of a diagnostic payload for a numeric payload is a
change in the response contract, not a change in presentation.

---

## 3. Invention B — Single-rule dual-invocation benefit adjudication

*Quoting a patient's share before dispensing, from the identical rule that will
later charge it.*

**Problem.** A patient on a medical aid scheme owes a shortfall. The dispensary
must state that figure while handing over the medicine; the till must collect
it minutes later. If the two are computed by different code, they differ, and
the patient is told one number and charged another.

**Conventional approach.** Compute the estimate from a pricing engine and the
charge from an adjudication engine. These are ordinarily separate subsystems
because they answer different questions (what should this cost / what did the
funder allow).

**What this system does.** The cover rule — which line categories the scheme
carries and at what proportion — is extracted to a single function invoked in
two directions:

1. **Prospectively**, over a basket that does not yet exist as a sale, priced on
   the same basis the sale will be priced on (shelf price), to quote the
   shortfall at the dispensary.
2. **Retrospectively**, over the sale's own lines, to adjudicate the claim.

The two invocations are then **verified to agree** by an executable check that
constructs a basket, quotes it, materialises it as a sale, adjudicates it, and
fails if the figures differ by more than half a cent.

**The specific trap this avoids** is documented in the code and is the
non-obvious part: the system already contained a pricing service computing a
"patient portion" from the scheme's *regulated* price — fee model, professional
fee, levy, and a maximum-medical-aid-price cap. That figure is arithmetically
correct and is **the wrong number**, because the sale a claim is raised against
is billed at shelf price. Two coherent calculations of two different things.
Using the available one would have been wrong by a plausible margin on every
scheme line.

---

## 4. Invention C — Custody-state settlement for off-premises collection

*Treating value held by a delivery agent as a distinct accounting state between
dispensary and till.*

**Problem.** Medicine leaves the building before it is paid for. Between the
counter and the patient's door the money belongs to nobody: the till has not
received it, the patient has not handed it over, and the agent carrying it is
neither a customer nor a cashier. Systems that model only "unpaid" and "paid"
have nowhere to put it.

**Conventional approach.** Mark the sale paid on dispatch (the shop's books show
money it does not have) or leave it unpaid until manually reconciled (the patient
appears to owe money they have already paid, and reconciliation is by hand).

**What this system does.** A delivery agent holds an **account** with two
figures that are deliberately never summed:

- **holding** — value collected at a door and not yet handed in. This is a debt
  the agent owes the pharmacy.
- **to collect** — value still on the road. This is owed by nobody, because the
  medicine has not changed hands.

Adding them produces a figure that is neither, and that is the figure that would
otherwise be entered into a cash reconciliation.

The state machine is:

```
dispensed → dispatched(agent)  … sale unsettled, agent "to collect"
          → collected(door)    … sale unsettled, agent "holding"
          → handed in(shift)   … sale SETTLED, agent clear
```

Three properties make this more than bookkeeping:

1. **Settlement writes through the identical tender primitive the counter uses**,
   so there is one definition of "has this been paid" rather than two that drift.
2. **The point-of-sale suppresses its collection controls** for any sale under
   agent custody, because a cashier collecting there takes money the agent is
   simultaneously collecting: the patient pays twice, or the agent returns with
   cash for a sale the books already show as settled.
3. **Dispatch is gated on the agent's running liability** against a per-agent
   limit, evaluated at the point the consignment is assembled rather than after
   the agent has left.

---

## 5. Invention D — Point-of-entry shorthand expansion with a never-print guarantee

*An abbreviation dictionary whose codes are structurally incapable of reaching
the patient.*

**Problem.** A dispenser types the same directions dozens of times a day. The
shortcut the dispenser needs and the words the patient needs are the same field,
so "one tablet three times a day after food" becomes `1t tds pc` **on the label**.
Abbreviations cause dispensing errors precisely because they are read by somebody
other than the person who wrote them — a patient at home, a nurse on a ward, a
locum the next morning.

**What this system does.** A per-tenant dictionary of 75 codes is expanded to
full natural language at the moment of entry. The code never becomes label text.
The safety argument is structural, not procedural: the only person who ever reads
a code is the dispenser who typed it, seconds after typing it.

Four features beyond simple substitution:

1. **Numeral–noun agreement.** `ii tab tds` expands to "TWO tablet*s*", not "TWO
   tablet". A post-expansion pass pluralises a countable noun immediately
   following a number word, on a closed list of dose-form nouns.
2. **Deliberate exclusion of ambiguous codes.** `od` means *once a day* in
   Southern African dispensing practice and *right eye* in the ophthalmic
   literature — both in daily use in one building. The system takes `od` as
   once-a-day and offers **no Latin laterality code at all**; eyes and ears are
   entered as `r-eye`, `l-eye`, `b-eye`, which cannot be read two ways and expand
   to the words written in full.
3. **Coverage disclosure as a first-class output.** The expander and the
   companion dose checker report what they did *not* cover. A clear result states
   "none of the limits held here was exceeded", never "safe", and names the
   medicines for which no limit is held.
4. **Client-mirrored expansion with server authority.** The rule is implemented
   twice — once on the server, which is authoritative because the label is
   rendered there, and once in the client, which yields a zero-latency live
   preview of the sentence that will print while the shorthand is still being
   typed. The field itself is never rewritten under the cursor.

A printable code book is generated **from the live dictionary**, so the copy an
inspector holds cannot disagree with the software.

---

## 6. Invention E — Negative-space regulatory register

*A compliance register that reports the documents you do not have.*

**Problem.** A pharmacy's licence to trade rests on a set of certificates from
different authorities with different renewal cycles. Every pharmacy manages this
in a lever-arch file and somebody's diary. The certificate that closes the shop
is the one nobody entered.

**Conventional approach.** A document repository. It can list what has been
uploaded; it cannot list what has not, because it has no model of what *should*
exist.

**What this system does.** The register is defined by an **expected set** for the
jurisdiction — 13 document kinds, each with its issuing authority, renewal
period, and a flag for whether trading is lawful without it. Every branch is
evaluated against the expected set, and an absent document is a first-class row
with its own state.

The consequence is a two-verdict distinction that a repository cannot produce:

- **"Cannot trade"** — a critical document is present and *expired*.
- **"Cannot be proved"** — a critical document has *never been recorded*.

These are different facts requiring different action, and conflating them either
alarms a compliant pharmacy or reassures a non-compliant one.

Documents are **superseded, never deleted**, forming a chain walkable in both
directions. A register answers "are we licensed today"; the chain answers the
question an inspection actually asks, which is "were we licensed in March".

---

## 7. Invention F — Reachability and presentation verification harness

*Executable checks for defects that compile, build, render, and are still wrong.*

**Problem.** A class of defect passes every conventional gate. The code
type-checks, the build succeeds, the page renders, no test fails — and the
capability is unreachable or the information is unreadable. Observed instances in
this system:

- A CSS class named by markup and defined nowhere: three separate facts rendered
  as one run-together string, on the screen a manager uses to decide who to
  telephone. Thirty-four such classes were found by one check.
- A hyperlink pointing at an authenticated API path: a browser navigation carries
  no `Authorization` header, so every attempt to open a licence certificate was
  refused — on the one screen whose purpose is producing that certificate.
- A component setting typography but not colour, inheriting a colour intended for
  a different surface: a patient's own name rendered near-black on a near-black
  card, invisible.
- A per-branch analysis filtering on a column that does not exist, raising an
  exception whose response carried no CORS headers — so the browser reported a
  cross-origin failure, naming the wrong cause in a different subsystem.

**What this system does.** 101 executable checks, each written to fail on a
specific defect that actually shipped, and each **verified in both directions**:
it must fire against the broken code and stay silent against the fixed code. The
harness reads across the client/server boundary — comparing the shape a client
asserts of a response against the shape the handler returns; comparing class
names used in markup against selectors present in stylesheets; comparing route
registration order against path specificity.

The discipline that makes it work is documented in the checks themselves: **a
check that reports a false positive is corrected in the check, not tolerated**,
because an audit that cries wolf is one people learn to skip. Several checks
record the false positives they produced and were narrowed.

---

## 8. Invention G — Hash-chained fiscal register with localised and honest verification

**What this system does.** Each fiscal receipt carries the hash of its
predecessor, forming a chain whose integrity is the evidentiary value of
fiscalising at all. Three refinements:

1. **Chain verification is localised per fiscal day** as well as across the whole
   register, so a break is attributable to a day rather than only to the estate.
2. **A sampled verification reports itself as partial.** An earlier
   implementation read the *oldest* 5,000 receipts while the interface claimed
   "all N receipts verify". A deliberate sample now takes the most recent and
   returns `partial: true`.
3. **The Z-report is computed from the receipts at read time**, not stored. A
   denormalised split invites disagreement with what it summarises, and the first
   time anybody notices is during an audit. Receipts carrying no tax are reported
   as "no VAT charged" rather than as zero-rated or exempt: those differ in a
   return, nothing on the receipt distinguishes them, and choosing one would put
   a guess into a statutory filing.

---

## 9. Invention H — Non-blocking clinical gating with named acknowledgement

**What this system does.** Clinical findings — interactions, dose maxima,
condition–ingredient contraindications, early-refill timing — do **not** hard-block
dispensing. Each requires a *named acknowledgement* that is captured and stored,
and the commit control is disabled until acknowledgement is given.

The reasoning is stated in the code and is the non-obvious part: refusing
outright on a small reference set teaches exactly the over-trust the checker
exists to prevent. A pharmacist told twice that the system checks doses will
trust it the third time, and the drug it does not hold is the one that goes out
at four times the maximum. So the system's coverage limits are displayed
alongside every result, and a line about which nothing is known is **named**
rather than passing silently.

---

## 10. Invention I — Derived progress state that cannot contradict its control

**What this system does.** A multi-step capture screen displays step completion
derived on every render from *the same predicates that gate the commit control*,
rather than from a stored cursor. A stored cursor goes stale the moment somebody
edits a completed step, and a progress display that can disagree with the button
tells the operator they are finished while the control they want stays disabled.

The display gates nothing, disables nothing, and moves focus only on an explicit
click. Two alternatives were considered and rejected for stated reasons:
auto-advancing focus moves the cursor while somebody is typing (on a
controlled-drug entry, a quantity in the wrong field, in a register an inspector
reads), and per-step modal dialogs hide the allergy, funder-standing and
basket information the screen exists to keep in view.

---

## 11. Candid novelty assessment — read before drafting

Counsel should treat this section as the applicant's own view of where the
strength lies. Filing broad claims over the weak items risks the whole
application.

| # | Candidate | Assessment | Recommended posture |
|---|---|---|---|
| A | Trust-gated metric publication | **Strongest.** Data-quality frameworks gate *pipelines*; this gates the *published figure at read time and substitutes a diagnostic*. The specific cross-source invariants are concrete and reducible to claim language. | Independent claim |
| C | Custody-state settlement | **Strong.** Cash-on-delivery is old. The combination of a two-figure agent account that is never summed, till-side control suppression keyed on custody state, settlement through the identical tender primitive, and dispatch gating on running liability is specific. | Independent claim |
| E | Negative-space regulatory register | **Strong.** Reporting the absent expected document, with the expired/never-recorded verdict split and a bidirectional supersession chain, is materially different from document management. | Independent claim |
| B | Single-rule dual-invocation adjudication | **Moderate.** The idea of one rule serving quote and charge is natural once stated; the *executable parity verification* is the defensible element. | Independent claim, narrowed to the verification |
| D | Shorthand expansion, never-print | **Moderate.** Sig-code expansion exists in dispensing software and is likely prior art. Numeral–noun agreement, the deliberate exclusion of ambiguous laterality codes, and generating the inspection document from the live dictionary are narrower and more defensible. | Dependent claims; do not claim expansion alone |
| F | Verification harness | **Moderate.** Static analysis and linting are extensive prior art. The cross-boundary reachability checks and the bidirectional self-test requirement may be claimable as a method. | Independent claim, drafted narrowly |
| H | Non-blocking gating with acknowledgement | **Moderate–weak.** Clinical decision support with override capture is well-established. The *coverage disclosure* output may be narrowly claimable. | Dependent claim |
| G | Fiscal chain | **Weak.** Hash-chained receipt registers are prior art and much of the design is mandated by the revenue authority's specification. The partial-verification honesty and per-day localisation are minor. | Describe; do not claim independently |
| I | Derived progress state | **Weak.** A UI pattern. | Describe only |
| — | Automatic tenant scoping by ORM session interception | **Likely prior art.** Row-level security and SQLAlchemy session events are standard. Described in the specification for completeness. | Describe only; do not claim |

**Two further cautions.**

*Jurisdictional coupling.* Several inventions are described against Zimbabwean
regulation (MCAZ licensing, ZIMRA fiscalisation, medical-aid shortfall practice).
Claims should be drafted at the level of the mechanism — "an expected document
set for a jurisdiction", "a statutory receipt register" — so protection is not
confined to one country's rules.

*Software-patent eligibility.* In several jurisdictions a claim must recite a
technical effect beyond automating a business method. The strongest technical
framings available here are: (A) a change in the *response contract* of a
computation, not merely its presentation; (C) a state machine over value custody
with control-surface suppression derived from that state; (E) evaluation against
a declared expected set producing a distinct verdict for absence; (F) analysis
across a client/server boundary detecting unreachable capability. Counsel should
foreground those framings.

---

## 12. Enablement material available

- Complete source: 48,000 lines of application server code, 92 entities, 461
  endpoints, 90 client screens.
- 101 executable verification checks, each demonstrating the defect it prevents.
- 253 commits, each with a written rationale that records the alternative
  considered and rejected — useful evidence of non-obviousness where an obvious
  approach was tried and found wrong.
