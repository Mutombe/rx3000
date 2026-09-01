# Reporting, till operations, claims and backup: implementation plan

Written from photographs of the incumbent system in use at Care Xpress Pharmacy
Central, taken 15 August 2026. Sixty-seven distinct screens; this plan is built
from a read of roughly a dozen of the most structural ones (every top-level menu
of all four applications, the cash-up procedure, the backup dialog and the
claims module). The remaining screens are mostly individual report outputs,
which refine layout rather than change the shape of the work.

## 1. What we are actually competing with

The incumbent is not one product. It is **four separate Windows applications**
sharing a Firebird database at `C:\RXWIN\DB\PHARM.GDB`:

| App | Version | Owns |
|---|---|---|
| **RxWin** | — | Dispensing, scripts, repeats, ScheduleX register, e-scripting |
| **POSWin** | 1.7.57 | Till, invoicing, cash-up, debtors, loyalty |
| **StockWin** | 1.4.26 | Stock control, creditors, purchasing, bin locations |
| **RecWin** | — | Medical aid claims reconciliation, ERA, batch payments |

Between them they expose roughly **120 named reports**. That number is the
competitive fact worth internalising: a pharmacy manager evaluating us will open
the Reports menu, and a short menu reads as an unfinished product regardless of
how good the individual screens are.

**The strategic conclusion is not "write 120 report screens".** Four apps with
four report menus is exactly why their reports are inconsistent — some export to
Excel, some print only, each has its own date-range control. Our advantage is
one system with one report engine. Build the engine, then reports become
declarations rather than screens, and 120 becomes tractable.

## 2. The report engine

Before any individual report, build the thing that makes the rest cheap.

**A report is a declaration**, not a page:

```python
Report(
    key="department_sales",
    title="Department sales",
    module="pos",
    params=[DateRange(), Optional("branch"), Optional("assistant")],
    columns=[...],
    query=lambda db, p: ...,
    totals=["amount", "units"],
    drill=lambda row: f"/pos/sales?department={row.code}",
)
```

The engine supplies, once and identically for every report:

- Date range, branch, till, assistant, department filters
- Pagination with a true total (never a bare `.limit()`)
- Sort, and column totals in the footer
- **Export to CSV, Excel and PDF**: the incumbent's Excel export is the single
  most-used feature in those screenshots; every one of the photographed reports
  has an Excel button and the taskbar shows a spreadsheet permanently open
- Print, including to a narrow receipt printer where that makes sense
- Save as a named view ("my Monday morning report")
- Schedule to email or WhatsApp on a cron
- A drill-down target, so a total is never a dead end

**Effort:** ~1 week for the engine. Each report thereafter is hours, not days.

**This is also where we beat them outright.** Their reports are static grids.
Ours get: charts where a shape matters more than a figure, comparison to the
prior period, and the AI summary already wired into the system reading the
result set and saying what changed.

## 3. Report catalogue

Grouped by our module structure, not theirs. Reports marked **new** have no
equivalent in the incumbent and are where we get ahead.

### Till and cash (POS)
Daily totals · Sales by hour **new** · Monthly sales summary · Department sales ·
Cash analysis · Cash control · Day end · Last till run and cash-up date ·
Assistant/cashier report · Assistant cash-up · Cashier variance league **new** ·
Void and cancelled transactions · Price override log · Refunds and returns ·
Outstanding CODs · Cancelled CODs · Transferred CODs · Outstanding lay-byes ·
Petty cash · Cash-back analysis · Rounding analysis · Till kickout log ·
Loyalty points earned/redeemed · Extra fee analysis · Quote reprints ·
Invoice reprints · Serial number report · Drivers report · Contact info ·
Security report · Log audit

**Detail registers, one per tender:** cash · credit card · cheque · voucher ·
direct banking · mobile money (EcoCash) · cellphone voucher

### Stock and procurement
Stock on hand · Stock valuation (at cost, at retail, at average) **new** ·
Stock on-hand gross profit · Stock usage per item · Stock usage and history ·
Min–max order report · Stock on order · Reorder suggestions · Slow movers **new** ·
Dead stock **new** · Expiring within N days **new** · Expired stock · Write-offs ·
Negative stock exceptions **new** · Bin location reports · Department reports ·
Manufacturer reports · Specials · Promotion labels · Markup report ·
Order price difference · Compare invoice cost to SEP · Compare cost/retail/avg
to SEP · Purchase orders · Total purchases · Schedule purchase report ·
Goods received not invoiced **new** · Supplier price file variance ·
Stock take variance **new** · Branch transfers in transit · Manufacturing report ·
Stock/rep flag reports · Assistant capture report

### Creditors
Creditor age analysis · Creditor statements · Remittance advice **new** ·
Payments due this week **new** · Purchases by supplier · Supplier performance
(fill rate, lead time, price drift) **new**

### Debtors
Debtor age analysis · Debtor statements · Cash debtor transactions ·
Overdue letters **new** · Credit limit exceptions **new** · Bad debt provision

### Dispensary
Script analysis · Drug usage · Tariff usage · ScheduleX register (full and
summary) · Script book · Repeats not recently filled · Future repeats ·
Script change history · Repeats change history · Outstanding OTCs ·
Last patient visit · Members report · Dispenser productivity ·
Script price changes · Price update changes · Generic substitution rate **new** ·
Schedule 5/6 register reconciliation **new**

### Claims (see §5)
Outstanding script payments (all / script range / date range / other rejection
codes) · Scripts per medical aid · Scripts per pay office · Scripts per debtor ·
Scripts per batch payment · Total age analysis · Age analysis per pay office ·
Batch payment · Rejection reason analysis **new** · Days-to-payment by scheme **new** ·
Claim resubmission tracker **new**

### Financial (built)
Trial balance · Income statement · Balance sheet · Cash flow · Aged analysis ·
VAT return · Journal report

## 4. Till operations and cash-up

This is the most operationally important part of the plan, because it is what a
cashier touches every single day and where the incumbent is strongest.

### What their cash-up does

Keyed on **Till No / Run Number / Draw No**. A "run" is a shift's trading; saving
the cash-up increments the run number and closes it. The screen shows every
invoice in the run, then reconciles:

```
                Cash+(U)+Float   Cr Card   Zapper   Cheques   Vouch/Pnts   Direct   Total
Counted              …              …        …         …           …         …        …
System               …              …        …         …           …         …        …
Difference           …              …        …         …           …         …        …
```

Plus: tomorrow's float, cash in till, rounding total, void total, till kickout,
unspecified payment methods, total points paid.

**Coinage Analysis** is a denomination-by-denomination physical count — notes and
coins entered separately, totalled, and compared to expected.

### What we build

Same skeleton, four improvements:

1. **Blind count.** The counter does not see the expected figure until they have
   committed their count. Showing the target first is an invitation to type it
   in, and a cash-up that always balances is telling you nothing. This is the
   single biggest control improvement available and it costs nothing.
2. **Denominations from the jurisdiction pack.** Their screen shows £ notes,
   which is a locale default nobody changed. Ours reads USD and ZWG
   denominations from the pack, and counts each currency's drawer separately —
   a dual-currency till is the norm in Zimbabwe and a single total is useless.
3. **Variance is a record, not a number on a screen.** Over and short are posted
   to a cash-variance account, attributed to the cashier, and trended. "Which
   cashier is repeatedly 5 dollars short" is a question their system cannot
   answer and ours should answer on one screen.
4. **A variance over a threshold requires a second person.** Not a second
   prompt: a different user's PIN, on the same principle as §7.

### Mid-shift operations
Drawer open without a sale (logged, reason required) · Cash drop to safe ·
Float in/out · Pick-up · Paid-out (petty cash) · X-reading (mid-shift totals,
non-destructive) · Z-reading (closes the run)

## 5. Card and mobile payment integration

The terminal in use is a **Verifone X990 on CABS**. This is an Android-based
smart terminal, which is good news: it is the generation that supports
integration rather than the standalone generation that does not.

**The goal:** the cashier never re-keys an amount, never waits for the terminal's
slip, and never reconciles two records by hand. The sale total goes to the
terminal; the approval, auth code, last four digits, scheme and terminal ID come
back and attach themselves to the sale.

**Three viable routes, in order of preference:**

1. **Semi-integrated ECR.** Our till sends the amount over USB, serial or TCP;
   the terminal takes the card and returns a structured result. This is the
   standard model and the one that requires least from us.
2. **Cloud/API pairing.** Some acquirer stacks expose a REST endpoint where a
   payment intent is created and the terminal polls for it. Better over a
   network, worse when the internet is down, which matters here.
3. **An app on the terminal itself.** The X990 runs Android, so in principle our
   till could run on it. Highest effort, and it puts us inside the acquirer's
   certification process.

**The blocker is commercial, not technical.** CABS controls what the terminal
will talk to, and the ECR interface has to be enabled and documented for us. The
first action is a conversation with CABS's merchant services asking for the ECR
integration specification for the X990 estate, not a line of code.

**What to do meanwhile:** we already have a `deviceAgent` abstraction with
`takePayment`, and the till already captures auth code, reference, last four,
scheme and terminal ID manually. That path stays as the fallback and the offline
mode. The integration becomes a driver behind an interface that already exists,
which is why this is a contained piece of work once the spec arrives.

**Mobile money (EcoCash)** follows the same shape and is arguably more valuable
in Zimbabwe: push a request to the customer's handset, poll for confirmation,
attach the result to the sale. The abstraction already anticipates this.

## 6. Claims and NH263

NH263 is the national health claims switch. The incumbent's RecWin shows the
shape this has to take, and the vocabulary matters because it is what the
pharmacy's staff already use:

- **Medical aid**: the scheme
- **Pay office**: the branch of the scheme that actually settles; a scheme can
  have several, and they pay at different speeds, which is why "age analysis per
  pay office" exists as its own report
- **Batch payment**: schemes pay in batches, not per script
- **ERA (Electronic Remittance Advice)**: the file the scheme returns saying
  what it paid, what it short-paid and what it rejected
- **Rejection codes**: and specifically "outstanding scripts with OTHER
  rejection codes", meaning the ones that need a human

**The work, in order:**

1. **Claim submission to NH263** — real-time where the switch supports it, batch
   where it does not. Needs the NH263 integration specification.
2. **The claim lifecycle as a first-class object**: prepared → submitted →
   acknowledged → adjudicated → paid / short-paid / rejected → resubmitted.
   Every transition timestamped and attributed.
3. **ERA import and auto-matching.** Load the remittance, match to submitted
   scripts, and post: cash received, scheme discount, patient co-payment,
   write-off. The unmatched remainder is the work queue.
4. **Rejection handling.** A rejection code must arrive with what to do about
   it, not just a number. Codes that are fixable get a resubmit action.
5. **Reconciliation to the ledger.** Scheme debtors on the balance sheet must
   equal the sum of unpaid claims, and the day it does not is the day something
   was posted around the subledger. We already have the control-account
   machinery for this.

## 7. Password-gated operations

The incumbent confirms the pattern — "Override Password for Category: MANAGER"
guarding assistant report access. Our list, on the principle that this is a
**second person, not a second prompt**:

Drawer open without a sale · Price and discount overrides beyond a threshold ·
Cash-up variance beyond a threshold · Alter payment method after the fact ·
Void or refund after cash-up · Stock write-offs · Stock take adjustments ·
Period close and reopen · Controlled-register corrections · Company profile ·
User management and role changes · Backup restore

## 8. Backup

Their dialog: destination directory, date-stamped archive name, a remote drive,
a second drive, retention count, disk space, and a list of existing archives.

**One detail in that screenshot is the whole design brief.** The archive list
shows `D20260809.ZIP — 0.00 MBytes`. That is a backup that failed and is sitting
in the list looking exactly like a successful one. A pharmacy discovers this on
the day it needs to restore.

**So ours verifies.** After writing, reopen the archive, check it is readable,
check row counts against the live database, and record the result. A backup is
not "a file was written", it is "a file was written and proven restorable".

**The behaviour you specified:**

| Context | Local | Cloud | Default |
|---|---|---|---|
| Desktop, online | offered | offered | user's choice, remembered |
| Desktop, offline | offered | unavailable, and said so | local, automatically |
| Web | offered (downloads) | offered | user's choice |

Plus: automatic nightly backup (already scheduled), retention policy, restore
with a confirmation naming what will be overwritten, and a visible "last good
backup" indicator — because the useful question is never "is backup configured"
but "when did one last actually work".

## 9. Sequence

| Phase | Work | Why here |
|---|---|---|
| **1** | Report engine + export/print/schedule | Everything else multiplies off it |
| **2** | Cash-up and till operations | Daily-touch, biggest competitive gap |
| **3** | Stock and procurement reports (~30) | Largest catalogue, engine makes it fast |
| **4** | Backup: verification, cloud/local, restore | Contained, and currently a real risk |
| **5** | Claims lifecycle + ERA import | Large; start once NH263 spec is in hand |
| **6** | POS/dispensary/debtor reports (~40) | Fill out the menu |
| **7** | Card terminal driver | Gated on CABS, not on us |
| **8** | Password-gated operations | Cuts across everything, so it lands late |

Phases 1–4 are the ones that change what a demo feels like.

## 10. What I need from you

1. **NH263 integration specification** — cannot be guessed at, and it gates
   phase 5.
2. **CABS merchant services contact** so I can request the X990 ECR spec.
3. **Cloud backup destination** — our own storage, or the pharmacy's own
   Google Drive / OneDrive? This changes who holds patient data and therefore
   what we have to promise about it.
4. **The offline dispensing question, still open:** may an offline till dispense
   prescriptions, or only sell front-shop items? Everything about offline mode
   hangs off this.
5. **Photographs of individual report outputs** where the exact columns matter to
   you — I have the menus and the structure, but not every grid.
