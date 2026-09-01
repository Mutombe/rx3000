"""What the incumbent does, and whether RX5000 does it yet.

The system being displaced is **Propharm / RxWin** (ComputASSIST Group, supported
by WildTech Solutions): a Win32 application on an embedded Firebird database
shared over a Windows file share, version 1.9.55.

Its weaknesses are real - LAN-only, one database file on a share, a licence that
expires, no web or mobile surface - but none of that is why a pharmacy would
stay with it. They would stay because it *works* and because their staff can
drive it without thinking. Every function below is one a pharmacist currently
performs by muscle memory, and any one of them missing is a reason not to
switch, regardless of how much else is better.

So this register is deliberately unflattering. `state` is what a pharmacist
would say after using RX5000 for a day, not what the code aspires to:

    done      a pharmacist could do this today and would not notice a loss
    partial   the capability exists but not the workflow, or not the shortcut
    missing   not built

`why_it_matters` is the thing to read when tempted to skip an item. Most of
these look small and are not: "To Follows" is a shelf of owed medicine that a
pharmacy tracks on paper if the software will not, and a pharmacy that has to
keep paper will keep the software that avoids it.
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Feature:
    key: str
    name: str
    area: str                    # dispensing | pos | stock | claims | reports | system
    state: str                   # done | partial | missing
    incumbent: str = ""          # how Propharm exposes it, verbatim where known
    why_it_matters: str = ""
    rx5000: str = ""             # where ours lives, or what is missing
    shortcut: str = ""           # the key the incumbent's users already know


REGISTRY: dict[str, Feature] = {}


def register(feature: Feature) -> Feature:
    REGISTRY[feature.key] = feature
    return feature


def by_area() -> dict:
    out: dict[str, list] = {}
    for f in sorted(REGISTRY.values(), key=lambda x: (x.area, x.name)):
        out.setdefault(f.area, []).append(f)
    return out


def summary() -> dict:
    counts: dict[str, int] = {}
    for f in REGISTRY.values():
        counts[f.state] = counts.get(f.state, 0) + 1
    total = len(REGISTRY) or 1
    return {
        "total": len(REGISTRY),
        "counts": counts,
        "parity_percent": round(100 * counts.get("done", 0) / total, 1),
        "blocking_switch": [f.key for f in REGISTRY.values() if f.state == "missing"],
    }


# ---------------------------------------------------------------------------
# Dispensing — the screen a pharmacist lives in
# ---------------------------------------------------------------------------

register(Feature(
    key="disp.new_script", name="New script", area="dispensing", state="done",
    incumbent="Dispensing > New Script", shortcut="Ctrl+N",
    rx5000="POST /api/prescriptions",
    why_it_matters="The core transaction."))

register(Feature(
    key="disp.otc_script", name="Over-the-counter script", area="dispensing",
    state="done", incumbent="Dispensing > Over The Counter Script", shortcut="Ctrl+O",
    rx5000="POST /api/dispensing/otc",
    why_it_matters="Pharmacist-initiated supply, recorded but without a prescriber."))

register(Feature(
    key="disp.to_follows", name="To Follows (owed medicine)", area="dispensing",
    state="done", incumbent="Dispensing > To Follows", shortcut="Ctrl+T",
    why_it_matters="The patient has paid for a full script but stock ran out, so the "
                   "pharmacy owes them the balance. Without this the debt lives on a "
                   "paper note by the till. And a pharmacy that must keep paper will "
                   "keep the software that avoids it. Probably the single most "
                   "switch-blocking item in this list.",
    rx5000="services/to_follows.py and /api/to-follows. A dispense may hand over "
           "less than the script asks; the balance becomes a debt, settled later "
           "through the ordinary FEFO path. /api/to-follows/ready goes further "
           "than the incumbent: it lists what is owed *and now in stock*, which "
           "is the call list rather than the ledger."))

register(Feature(
    # `name` is what our screen says, `incumbent` what theirs says. They differ
    # here on purpose: the dispensary asked for "N-Repeat", and the register is
    # only useful if it keeps reporting the incumbent's wording accurately.
    key="disp.unfinished", name="N-Repeats", area="dispensing",
    state="done", incumbent="Dispensing > Unfinished Scripts", shortcut="Ctrl+U",
    why_it_matters="A script half-captured when the phone rings must be resumable. "
                   "Without it the pharmacist re-keys everything, and re-keying is "
                   "where dispensing errors come from.",
    rx5000="A draft holds no Rx number. A number burnt on an abandoned capture "
           "would leave a gap in a numbered register that somebody has to "
           "explain. And cannot be dispensed. /api/prescriptions/unfinished is "
           "the resume queue; finalise takes the next number in sequence."))

register(Feature(
    key="disp.temp_save", name="Temp save", area="dispensing", state="done",
    incumbent="Temp Save button on the script screen",
    why_it_matters="The same need mid-script rather than mid-queue.",
    rx5000="PUT /api/prescriptions/{id}/draft. The item list is replaced rather "
           "than merged: the pharmacist has the whole script in front of them, "
           "and a merge would silently keep a line they had just deleted."))

register(Feature(
    key="disp.alter_script", name="Alter script", area="dispensing", state="done",
    incumbent="Dispensing > Alter Script", shortcut="Ctrl+B",
    why_it_matters="Correcting a script after capture without voiding and re-keying it.",
    rx5000="POST /api/prescriptions/{id}/alter. A dispensed line cannot be "
           "altered. The register would stop matching the medicine, and every "
           "correction is written into the script with a reason and a name."))

register(Feature(
    key="disp.quick_pricing", name="Quick pricing", area="dispensing", state="done",
    incumbent="Dispensing > Quick Pricing", shortcut="Ctrl+Q",
    why_it_matters="A patient asks what something costs on their scheme. Answering "
                   "in seconds without starting a script is a counter-speed feature "
                   "staff use constantly.",
    rx5000="POST /api/quick-price. Separates what the scheme pays from what the "
           "patient pays, because the patient is asking the second question, and "
           "says plainly that it is an estimate, not the funder's adjudication."))

register(Feature(
    key="disp.repeats_future", name="Future repeats and future-dated scripts",
    area="dispensing", state="partial",
    incumbent="Dispensing > Future Repeats / Future dated Scripts",
    why_it_matters="Chronic patients are the reliable revenue. Knowing who is due, "
                   "and being able to capture a script dated ahead, is how a pharmacy "
                   "keeps them.",
    rx5000="/api/repeats/due is the call sheet, overdue first, with stock "
           "checked so nobody telephones a patient they cannot serve. "
           "Future-DATED capture is still absent."))

register(Feature(
    key="disp.reprint", name="Reprint script and labels", area="dispensing",
    state="done", incumbent="Dispensing > Reprint Script / Reprint Labels",
    shortcut="Ctrl+P / Ctrl+L",
    why_it_matters="Labels jam, peel, and get stuck to the wrong box. Reprinting is "
                   "a daily action, not an exception.",
    rx5000="POST /api/reprints returns the label data and records the reprint. "
           "A second label for a controlled substance is the easiest way to make "
           "one dispensing look like two, so who reprinted what is kept."))

register(Feature(
    key="disp.interactions", name="Drug interaction checking", area="dispensing",
    state="partial", incumbent="Interactions tab on the script screen",
    why_it_matters="Clinical safety, and the one gap a pharmacist will judge the "
                   "software on. Needs an interaction data source; the check itself "
                   "is straightforward once there is one.",
    rx5000="services/interactions.py holds a dozen established high-severity "
           "pairs plus duplicate-therapy detection. Every answer carries its "
           "coverage and a clear result is worded 'none of the pairs this system "
           "holds', never 'no interactions'. A partial list read as safety is "
           "more dangerous than no list. A licensed database replaces one module."))

register(Feature(
    key="disp.patient_messages", name="Patient / member / scheme messages",
    area="dispensing", state="done",
    incumbent="Tabs: All & Allergies, Patient Mess, Member Mess, MedAid Mess, MA UserMess",
    why_it_matters="Notes that must surface at the moment of dispensing, an allergy, "
                   "a scheme rule, a debt. A note nobody sees at the counter is not a note.",
    rx5000="services/messages.py and /api/messages/for-dispensing assemble every "
           "note in one call. Severity 'stop' refuses the dispense until somebody "
           "acknowledges it by name. Recorded patient allergies are folded in "
           "automatically. A system that only warned about allergies somebody "
           "remembered to re-enter as a note would be reassuring and wrong."))

register(Feature(
    key="disp.line_flags", name="No-claim and not-dispensed line flags",
    area="dispensing", state="done",
    incumbent="N/C and N/D columns, NoClaim[F3] and Not Disp[F4]",
    why_it_matters="One line on a script may be cash while the rest is claimed, or "
                   "may not be dispensed at all. Without per-line flags the pharmacist "
                   "splits the script by hand.",
    rx5000="claims_engine.claimable_lines() excludes them, so a cash line is "
           "never claimed for. Sale lines now carry prescription_item_id, which "
           "is what makes a script's billing decisions reachable from the sale."))

register(Feature(
    key="disp.supply_days", name="Supply days", area="dispensing", state="partial",
    incumbent="Supply Days field, default 30",
    why_it_matters="Schemes adjudicate on days of supply, not just quantity. It "
                   "drives repeat timing and rejection reasons.",
    rx5000="PrescriptionItem.supply_days is captured; nothing consumes it yet."))

register(Feature(
    key="disp.margin_live", name="Live margin while dispensing", area="dispensing",
    state="done", incumbent="GP % on entry; Cost and Profit % in the totals bar",
    why_it_matters="The pharmacist sees profitability as they price, not in a report "
                   "next month. It is how a good dispenser protects the business.",
    rx5000="Carried on /api/script-totals per line and in total, how a dispenser "
           "notices they are about to sell below cost, rather than reading it in "
           "a report next month."))

register(Feature(
    key="disp.totals_bar", name="Full totals breakdown", area="dispensing",
    state="done",
    incumbent="RxGross, Gross, Nett, NoClaim, SurCharge, Vat, Levy(R), Levy, "
              "TotLevy, Claim, Cost, Profit %",
    why_it_matters="Twelve figures the pharmacist reads at a glance to know the "
                   "script is right before finishing it.",
    rx5000="POST /api/script-totals returns all twelve plus per-line margin, and "
           "warns outright when a script sells below cost."))

register(Feature(
    key="disp.keyboard", name="Function-key driven workflow", area="dispensing",
    state="partial",
    incumbent="F1 Mix, F2 Oint, F3 NoClaim, F4 Not Disp, F5 WayBill, F6 Auth, "
              "F8 Repts, F9 Hist, F11 Claim Later, Ctrl+R RT Resp, F12 Finish",
    why_it_matters="Experienced staff never touch the mouse. Matching the keys they "
                   "already know removes most of the retraining cost of switching.",
    rx5000="frontend/src/keymap.ts now carries the incumbent's bindings verbatim "
           "as one source of truth, checked for conflicts. Wiring each screen to "
           "them is what remains. One deliberate divergence: F12 finishes a "
           "script there and here, but here it confirms first, the same key, a "
           "safer behaviour, because finishing is irreversible once fiscalised."))

register(Feature(
    key="disp.waybill", name="Waybill / delivery note", area="dispensing",
    state="done", incumbent="WayBill[F5]",
    why_it_matters="Medicine leaving the shop for a patient's home needs a document. "
                   "Also the hook for the future deliverer app.",
    rx5000="Waybill model and /api/waybills. A controlled item leaving the "
           "premises flags an identity check at the door, it never reaches the "
           "counter where that would normally happen, and a delivery cannot "
           "close without a name against it."))

register(Feature(
    key="disp.claim_later", name="Claim later", area="dispensing", state="done",
    incumbent="Claim Later[F11]",
    why_it_matters="The switch is down, or the member's card is not present. The "
                   "medicine still goes out and the claim is queued. Without it the "
                   "pharmacy either refuses the patient or loses the claim.",
    rx5000="claim_later on the settlement payload holds the claim instead of "
           "sending it; /api/claims/deferred is the queue and submit-all is what "
           "a pharmacy runs when the switch comes back. The patient is liable in "
           "full until the funder answers, because promising otherwise commits "
           "money nobody has agreed to."))

register(Feature(
    key="disp.realtime_reversal", name="Realtime reversals and logs", area="dispensing",
    state="done", incumbent="Dispensing > Realtime Reversals, Realtime Logs",
    why_it_matters="A claim sent in error must be reversed at the switch, and the "
                   "pharmacist must be able to see the conversation when a funder "
                   "disputes it.",
    rx5000="/api/realtime/log reads the switch conversation; "
           "/api/realtime/reverse/{txn} reverses a claim as its own transaction "
           "rather than by amending the original, what was sent is a fact, and "
           "a reversal is a second fact about it."))

register(Feature(
    key="disp.compound", name="Mixtures and ointments", area="dispensing",
    state="partial", incumbent="Mix[F1], Oint[F2], Mix No, Container, B/Bulk",
    why_it_matters="Extemporaneous preparation is core pharmacy work.",
    rx5000="services/compounding.py is complete, costing, inherited schedule, FEFO "
           "draw, but it is not reachable from the dispensing screen."))

register(Feature(
    key="disp.icd10_entry", name="ICD-10 on the script line", area="dispensing",
    state="done", incumbent="ICD10 Codes dropdown, List ICD10 Ctrl+1, Del Ctrl+Del",
    why_it_matters="A claim line without a diagnosis is rejected.",
    rx5000="PrescriptionItem.icd10_code, DiagnosisPicker, chapter-aware validation."))

register(Feature(
    key="disp.fee_model", name="Fee model on the script", area="dispensing",
    state="done", incumbent="Glb/Fee Model: SEP+50, FeeModel button, MMAP Active",
    why_it_matters="Regulated pricing is derived, never typed.",
    rx5000="FeeModel/FeeTier, services/pricing.py, MMAP cap."))

# ---------------------------------------------------------------------------
# Stock, POS and claims
# ---------------------------------------------------------------------------

register(Feature(
    key="stock.schedule_register", name="Schedule X register", area="stock",
    state="done",
    incumbent="Schedule X Register: start/end schedule, running Start/In/Out/Bal "
              "quantities, patient and doctor detail, print and Excel",
    why_it_matters="A legal record. Its absence is a licensing problem, not a "
                   "feature gap.",
    rx5000="RegisterEntry with running balance; /api/register."))

register(Feature(
    key="stock.excel_export", name="Excel export on every report", area="reports",
    state="done", incumbent="Print and Excel buttons on every grid",
    why_it_matters="Every pharmacy manager reconciles in a spreadsheet. A report "
                   "that cannot leave the system is a report they will not trust.",
    rx5000="/api/export/{dataset}, products, batches, claims, to-follows, "
           "journal, trial balance, accounts. CSV rather than a workbook: it "
           "opens in everything and needs no dependency."))

register(Feature(
    key="claims.medaid_matrix", name="Scheme configuration matrix", area="claims",
    state="partial",
    incumbent="Medical Aid Printing: pay office, medaid code, realtime enabled, "
              "disabled, levies, discounts, exclusions, destination codes, fee model",
    why_it_matters="Every scheme has its own rules and the pharmacy must see and "
                   "edit them in one grid.",
    rx5000="MedicalAid carries pay office, fee model, levies, discounts, formulary "
           "and realtime; there is no single configuration grid over them."))

register(Feature(
    key="claims.biometric", name="Biometric member verification", area="claims",
    state="partial", incumbent="Realtime schemes marked BIOMETRIC in the scheme list",
    why_it_matters="Several Zimbabwean schemes will not adjudicate without it.",
    rx5000="Full flow built and proven against a simulator; the Health 263 reader "
           "driver is not implemented."))

register(Feature(
    key="system.trading_period", name="Trading period", area="system",
    state="done", incumbent="Trading Period 202606, shown on every screen and "
                               "used to scope reports",
    why_it_matters="The accounting period everything is filed under. It is the spine "
                   "of the accounting module still to be built, and reports scoped "
                   "by date rather than period will not reconcile to a ledger.",
    rx5000="services/periods.py, /api/periods and the Periods screen. A closed "
           "period refuses postings; closing freezes the signed-off figures and "
           "any later drift is reported rather than hidden. The ledger asks it "
           "before every journal entry."))

register(Feature(
    key="system.station", name="Station identity and licensing", area="system",
    state="done",
    incumbent="Station No, Version, Build, Server Share Name, DB Server Name, "
              "Software Expiry, all visible in a permanent System Information panel",
    why_it_matters="A product sold to many pharmacies needs to know which till it is "
                   "on for support and for licensing.",
    rx5000="services/station.py and /api/system/info. The licence warns and "
           "never blocks, refusing to open a till over a billing matter puts "
           "patients between a vendor and its invoice."))

register(Feature(
    key="system.backup", name="Backups from inside the product", area="system",
    state="done", incumbent="BackUps button in the main toolbar",
    why_it_matters="A pharmacy will not run its own database backups. If the product "
                   "does not do it, nobody does, and one disk failure ends the business.",
    rx5000="Not built."))

register(Feature(
    key="system.step_up_auth", name="Password on sensitive actions", area="system",
    state="done",
    incumbent="Certain functions re-prompt for a password before opening",
    why_it_matters="Being logged in is not authorisation for everything. Price "
                   "overrides, voids, register access and scheme edits are where "
                   "loss happens, and a shared till is often left unlocked.",
    rx5000="services/stepup.py, /api/step-up and the StepUp prompt. Single-use, "
           "single-action, three-minute grants; void and price override refuse "
           "self-approval so a supervisor must enter their own password. Every "
           "attempt is logged including refusals, repeated refusals on one till "
           "is what theft looks like from outside."))
