# RX5000 — Claims

**Draft claim set for patent counsel.**
Claims are grouped by invention. Within each group the independent claim states
the mechanism at its broadest defensible scope; dependent claims narrow it toward
the embodiment. Reference numerals in parentheses refer to the figures in
`02-description.md`.

Section G records the applicant's view of what is **not** claimed and why, so
counsel does not spend examination defending prior art.

---

## Group A — Trust-gated metric publication

*Primary independent claim. See FIG. 7.*

**1.** A computer-implemented method of producing a derived operational metric
from a plurality of independently maintained record sets held in a database, the
method comprising:

&nbsp;&nbsp;(a) receiving a request for the metric over a defined reporting
period;

&nbsp;&nbsp;(b) retrieving a first record set and a second record set, each of
which independently satisfies the schema constraints of the database;

&nbsp;&nbsp;(c) evaluating, **at the time of the request and before computing the
metric**, a semantic invariant relating a quantity derived from the first record
set to a quantity derived from the second record set, the invariant being a
condition that must hold if the two record sets describe the same underlying
events;

&nbsp;&nbsp;(d) where the invariant holds, computing the metric and returning a
response payload comprising the metric together with a validity indicator in a
first state; and

&nbsp;&nbsp;(e) where the invariant does not hold, **withholding the metric** and
returning a response payload comprising the validity indicator in a second state,
one or more diagnostic counts establishing the failure of the invariant, and a
natural-language explanation identifying the inconsistency between the record
sets,

&nbsp;&nbsp;such that a client rendering the response displays the explanation in
the position the metric would have occupied.

**2.** The method of claim 1, wherein the first record set comprises dispensing
records and the second record set comprises sale records, and the invariant
requires that a monetary total derived from the sale records is not less than a
monetary total attributable to the dispensing records they are matched to.

**3.** The method of claim 1, wherein computing the metric comprises deriving a
monetary quantity **only** from records carrying a recorded transaction price,
counting records lacking such a price as a non-monetary quantity, and including
in the response the number of records so excluded.

**4.** The method of claim 1, further comprising, where the metric can be computed
but is knowably incomplete because a proportion of source records cannot be
attributed to a requested dimension:

&nbsp;&nbsp;(a) computing the metric;
&nbsp;&nbsp;(b) computing the count and proportion of unattributable records;
&nbsp;&nbsp;(c) including in the response a statement that per-dimension figures
do not sum to the aggregate figure and the reason; and
&nbsp;&nbsp;(d) causing the client to render that statement **preceding** the
per-dimension figures in reading order.

**5.** The method of claim 1, wherein the record sets comprise a declared expected
set of regulatory documents and a held set of recorded documents, and the second
state of the validity indicator distinguishes a first verdict, indicating that a
required document is recorded and lapsed, from a second verdict, indicating that
a required document has never been recorded.

**6.** A system comprising a processor and memory storing instructions which when
executed cause the system to perform the method of any of claims 1 to 5.

---

## Group B — Single-rule dual-invocation benefit adjudication

*See FIG. 5.*

**7.** A computer-implemented method of settling a transaction part-funded by a
third-party benefit provider, comprising:

&nbsp;&nbsp;(a) storing a **single cover rule** determining, for a set of
transaction lines, a portion payable by the benefit provider;

&nbsp;&nbsp;(b) invoking the cover rule **prospectively** upon a provisional line
set that does not yet constitute a transaction record, the lines being valued on
the same pricing basis on which the eventual transaction record will be valued,
to produce a quoted beneficiary liability;

&nbsp;&nbsp;(c) displaying the quoted beneficiary liability at a first terminal
prior to release of goods;

&nbsp;&nbsp;(d) creating the transaction record and invoking the **same** cover
rule retrospectively upon the lines of that record to produce an adjudicated
provider portion and a charged beneficiary liability equal to the transaction
total less that portion; and

&nbsp;&nbsp;(e) collecting the charged beneficiary liability at a second terminal;

&nbsp;&nbsp;wherein the quoted and charged liabilities are equal by construction
because both derive from a single implementation of the cover rule.

**8.** The method of claim 7, further comprising executing an automated
verification procedure which:

&nbsp;&nbsp;(a) constructs a provisional line set;
&nbsp;&nbsp;(b) obtains a quoted liability by step (b) of claim 7;
&nbsp;&nbsp;(c) materialises the same line set as a transaction record;
&nbsp;&nbsp;(d) obtains a charged liability by step (d) of claim 7;
&nbsp;&nbsp;(e) asserts that the two agree within a rounding tolerance;
&nbsp;&nbsp;(f) asserts that the provider portion and the beneficiary liability
sum to the transaction total; and
&nbsp;&nbsp;(g) reports failure where either assertion does not hold.

**9.** The method of claim 7, wherein where the beneficiary has no valid
membership identifier the prospective invocation returns the whole transaction
value as the beneficiary liability together with a reason string, and that reason
is displayed at the first terminal before release of goods.

**10.** The method of claim 7, wherein the display at the first terminal presents
the provider portion and the beneficiary liability as separate labelled
quantities, together with a designation of the terminal at which the beneficiary
liability is to be collected.

**11.** The method of claim 7, wherein upon collection the system compares the
amount collected against the charged liability and, where the amount collected is
less, emits a notification stating the residual amount and its cause, rather than
a notification of successful settlement.

---

## Group C — Custody-state settlement for off-premises collection

*See FIG. 6.*

**12.** A computer-implemented method of accounting for value collected away from
a point of sale by a delivery agent, comprising:

&nbsp;&nbsp;(a) creating a transaction record in an unsettled state and a
consignment record associating the transaction record with a delivery agent and
an amount to be collected;

&nbsp;&nbsp;(b) maintaining, for each delivery agent, an account comprising **two
separately held quantities**:
&nbsp;&nbsp;&nbsp;&nbsp;(i) a *carried* quantity, being value collected by the
agent and not yet surrendered, constituting a liability of the agent to the
operator; and
&nbsp;&nbsp;&nbsp;&nbsp;(ii) an *outstanding* quantity, being value associated
with consignments not yet delivered, constituting a liability of no party;

&nbsp;&nbsp;(c) upon recording collection at the point of delivery, transferring
the amount from the outstanding quantity to the carried quantity **while leaving
the transaction record in the unsettled state**;

&nbsp;&nbsp;(d) upon the agent surrendering value into an open cash-handling
session, writing a tender record against the transaction record **using the same
tender-recording primitive used by the point of sale** and transitioning the
transaction record to a settled or part-settled state determined by the sum of
tender records against it; and

&nbsp;&nbsp;(e) suppressing, at the point of sale, controls for collecting
payment against any transaction record whose associated consignment is in a
dispatched or undelivered state, and displaying in their place an indication
identifying the agent holding the value.

**13.** The method of claim 12, wherein the two quantities of the agent account
are never presented as a single summed figure, and are labelled at the interface
to distinguish a liability of the agent from a liability of no party.

**14.** The method of claim 12, further comprising evaluating, at the moment a
consignment is assembled and before it is released, whether the agent's carried
quantity exceeds a stored per-agent limit, and refusing dispatch where it does.

**15.** The method of claim 14, wherein the assembling interface presents, for
each selectable agent, that agent's current carried quantity and an indication of
whether the agent exceeds the stored limit or holds a lapsed operating licence.

**16.** The method of claim 12, wherein the amount to be collected recorded on the
consignment comprises the beneficiary liability determined under claim 7 plus a
delivery charge, and **excludes** the portion payable by the third-party benefit
provider.

**17.** The method of claim 12, wherein upon surrender the system:
&nbsp;&nbsp;(a) records the amount counted as distinct from the amount expected
and retains the variance; and
&nbsp;&nbsp;(b) refuses, rather than truncates, any collected amount exceeding the
outstanding balance of its transaction record, and reports the refusal
identifying the consignment.

---

## Group D — Regulatory document register defined against an expected set

*See FIG. 8.*

**18.** A computer-implemented method of evidencing an operator's regulatory
standing, comprising:

&nbsp;&nbsp;(a) storing a declared **expected set** of document kinds for a
jurisdiction, each kind associated with an issuing authority, a renewal period,
and a criticality flag indicating whether lawful operation is possible without
it;

&nbsp;&nbsp;(b) storing a held set of document records, each associated with an
operating location, a kind, an expiry date where applicable, and a stored
representation of the document itself;

&nbsp;&nbsp;(c) evaluating the held set against the expected set to derive, for
every kind in the expected set, a state selected from at least: recorded and
current; recorded and within a first threshold of expiry; recorded and within a
second, shorter threshold of expiry; recorded and lapsed; recorded without an
expiry; and **never recorded**;

&nbsp;&nbsp;(d) deriving a location verdict which distinguishes a first verdict,
arising where a document of critical kind is recorded and lapsed, from a second
verdict, arising where a document of critical kind has never been recorded; and

&nbsp;&nbsp;(e) presenting the derived states for kinds in the *never recorded*
state as rows of equal standing to those for recorded documents.

**19.** The method of claim 18, wherein a document record is superseded rather
than deleted upon renewal, by storing a reference from the superseded record to
the superseding record, and the system provides traversal of the resulting chain
in both directions such that from an identifier of a lapsed document the current
document of that kind is reachable.

**20.** The method of claim 19, further comprising, upon a request to display a
superseded document, presenting an indication that it is not the current document
of its kind together with a reference to the document that replaced it, before
presenting the superseded document's own expiry date.

**21.** The method of claim 18, wherein the verdict for each operating location is
presented within a table of operating locations, is retrieved for all locations
in a single request rather than one request per row, and is rendered as
indeterminate rather than as a neutral value while retrieval is pending.

**22.** The method of claim 18, wherein a renewal is recorded by creating a new
document record rather than by amending the expiry date of the existing record,
whereby the evidence of the period covered by the existing record is preserved.

---

## Group E — Point-of-entry directions expansion

*See FIG. 4. Drafted narrowly — see Section G.*

**23.** A computer-implemented method of generating patient-facing dosage
directions, comprising:

&nbsp;&nbsp;(a) storing a per-operator dictionary mapping abbreviation codes to
natural-language expansions;

&nbsp;&nbsp;(b) receiving a shorthand string at a data-entry field;

&nbsp;&nbsp;(c) tokenising the string and substituting each token matching a
dictionary code with its expansion, **passing unmatched tokens through
unchanged**;

&nbsp;&nbsp;(d) applying a **numeral-agreement transformation** whereby a token
belonging to a stored set of countable dose-form nouns and immediately preceded
by a token denoting a quantity greater than one is replaced by its plural form;
and

&nbsp;&nbsp;(e) emitting the transformed string as the directions rendered on a
dispensing label, such that no abbreviation code appears in the rendered output.

**24.** The method of claim 23, wherein the dictionary excludes any code
denoting anatomical laterality that is homographic with a code denoting a dosing
frequency, and instead provides laterality codes containing a non-alphabetic
separator whose expansions state the laterality in full words.

**25.** The method of claim 23, wherein the expansion of step (c) is additionally
performed by a client application against a locally held copy of the dictionary
and rendered as a live preview adjacent to the data-entry field while the
shorthand remains in the field, the field contents themselves being left
unmodified until the field is committed.

**26.** The method of claim 25, further comprising identifying and displaying,
adjacent to the preview, those tokens of the shorthand string which matched no
dictionary code.

**27.** The method of claim 23, further comprising generating a printable document
from the dictionary at the time of the request, the document comprising each code,
its expansion, its origin, and, for codes stored with an ambiguity annotation,
that annotation, whereby a printed reference cannot differ from the dictionary in
force.

**28.** A method of clinical dose screening comprising parsing the shorthand of
claim 23 into a quantity per dose and a frequency, comparing the resulting daily
quantity against a stored maximum for the corresponding ingredient, and emitting
a result which, where no maximum is exceeded, states that no stored maximum was
exceeded and **names the medicines for which no maximum is stored**, and which
never asserts that the dose is safe.

---

## Group F — Cross-boundary reachability verification

**29.** A computer-implemented method of verifying an application comprising a
client and a server, the method comprising, without executing the client:

&nbsp;&nbsp;(a) parsing client source to extract, for each data-retrieval call, a
target path and an asserted response shape;

&nbsp;&nbsp;(b) parsing server source to extract, for each registered handler, a
path and a returned response shape;

&nbsp;&nbsp;(c) reporting each call whose asserted shape is incompatible with the
returned shape of the handler matching its path;

&nbsp;&nbsp;(d) parsing client markup to extract class identifiers applied to
rendered elements and stylesheet source to extract class identifiers appearing in
selectors, and reporting each applied identifier absent from every selector; and

&nbsp;&nbsp;(e) reporting each hyperlink in client markup whose target resolves to
a server path requiring an authorization header, on the basis that a browser
navigation does not transmit such a header.

**30.** The method of claim 29, further comprising reporting each registered
handler path which is preceded in registration order by a path containing a
parameter segment that would match a literal segment of the reporting path.

**31.** The method of claim 29, further comprising, for a stylesheet loaded
concurrently with a component stylesheet, identifying element-name selectors in
the former which declare a visual property, identifying elements styled by the
latter, and reporting each such element for which the component stylesheet
declares no value for that property.

**32.** The method of claim 29, wherein each reporting rule is accompanied by a
stored pair of assertions requiring that the rule reports a finding when applied
to a recorded defective state of the source and reports no finding when applied
to the corrected state.

**33.** The method of claim 29, further comprising executing each server routine
that accepts a dimension-narrowing parameter with a valid value of that parameter
against a populated data store, and reporting any routine that raises, on the
basis that an attribute or column absent from a model is not detected by static
type analysis and is reached only when the narrowing branch executes.

---

## Group G — Not claimed, and why

Counsel should be aware that the following are described in the specification for
enablement and are **not** proposed for claiming. Attempting to claim them is
likely to draw prior art and jeopardise the stronger groups above.

| Subject matter | Reason not claimed |
|---|---|
| Automatic tenant scoping by ORM session interception | Row-level security and ORM query-filter events are well-established. Described only. |
| Hash-chained receipt registers | Standard integrity construction; substantially mandated by the revenue authority's specification. The *per-day localisation* and *partial-verification disclosure* are minor and are offered only as dependent matter if counsel considers them worth pursuing. |
| Cash-on-delivery as such | Prior art. Group C claims the custody **state machine**, the two-quantity account, till-side control suppression, and dispatch gating — not collection at a door. |
| Sig-code expansion as such | Prior art in dispensing software. Group E claims numeral agreement, homograph exclusion, the client-mirrored live preview, and the dictionary-generated reference document. |
| Clinical decision support with override capture | Extensive prior art. Claim 28 is confined to the *coverage-disclosure* output. |
| Multi-currency tender recording | Ordinary practice in multi-currency retail. |
| The step-progress display | A user-interface pattern; described only. |
| Impersonation with audited dual principal | Common in administrative systems. |

---

## Group H — Figures required for filing

The schematics in `02-description.md` should be redrawn to formal patent
standards. The following are the figures the claims depend on:

| Fig. | Title | Supports claims | Notes for the draughtsman |
|---|---|---|---|
| 1 | System architecture | context | Four client types, middleware stack, service tiers, dual database target. |
| 2 | Entity relationships | 1–5, 12–17 | Emphasise that `Sale` carries a branch and `Prescription` does not — the attribution path runs Dispensing → Sale → Branch. |
| 3 | Dispensing flow, three settlement routes | 7–11, 12 | The three-way branch at the foot is the important element. |
| 4 | Directions expansion pipeline | 23–28 | Show the pass-through of unmatched tokens as a distinct path, and the client mirror as a parallel branch. |
| 5 | One cover rule, two invocations | 7–11 | Show the single rule box feeding both arrows, and the verification loop closing between the two outputs. |
| 6 | Custody state machine | 12–17 | Three columns (dispensary / road / till). The till-suppression box must be shown attached to the OUT and HOLDING states. |
| 7 | Trust-gated publication | 1–5 | Two inputs, one invariant diamond, two divergent outputs; the refusal path must show the diagnostic payload, not an error. |
| 8 | Expected set vs held set | 18–22 | Outer join producing per-kind states including *never recorded*; supersession chain with bidirectional traversal below. |
| 9 | Fiscal chain and day close | not claimed | Include for completeness. |
| 10 | Verification harness | 29–33 | Three source inputs converging on the check set; the bidirectional self-test annotation is the claimed element. |

Two additional figures should be drawn for filing that do not appear in the
description:

- **FIG. 11 — Sequence diagram, delivery round.** A UML-style sequence across
  Dispenser, System, Agent, Patient, Cashier, showing the sale remaining unsettled
  across three of the five interactions. Supports claims 12–17 more clearly than
  the state diagram alone.
- **FIG. 12 — Screen mock, split display and route selection.** A wireframe of the
  dispensing commit area showing the scheme portion, the shortfall, the three
  route controls, and the collection statement. Supports claims 10 and 16.
