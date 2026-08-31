"""Can you do anything on a detail page, or only read it?

A detail page that only reads is a printout. Somebody opens a repeat, a
delivery, a supplier, sees exactly what they needed to see — and then has to go
back to the list to act on it, or to another screen entirely, carrying the
record in their head. That is the shape of a report, and this is meant to be a
place of work.

For every detail page this reports:

    actions   a control that does something, in the page header where the eye
              goes for one
    modal     an action that asks before it acts
    goes      an action that hands over to another screen with the record
              travelling in the address

`goes` is the one worth explaining, because getting it wrong is invisible. When
a repeat is supplied, the medicine leaves the shelf and a sale is raised that
is still waiting to be paid. The repeats screen used to stop at a toast — so
the operator stood on the repeats list with a pending sale nobody had mentioned
and a patient in front of them, and the money was collected only if somebody
later remembered to go and find the invoice.

The handover has to carry the record. `/pos` passes nothing and lands a cashier
on an empty till; `/pos?settle=1841` opens the till on the sale. One is a link
and the other is a handover, and only the second is one movement of work.

    python qa/detail-actions.py
    python qa/detail-actions.py --gaps
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ROOT / "frontend" / "src" / "pages"

#: Pages that show one record. Everything else is a list or a dashboard.
DETAIL = [
    "PatientDetail", "ProductDetail", "PrescriptionDetail", "SaleDetail",
    "RepeatDetail", "DispensingDetail", "DriverDetail", "WaybillDetail",
    "ToFollowDetail", "ClaimDetail", "ClaimBatchDetail", "SupplierDetail",
    "PrescriberDetail", "StaffDetail", "ShiftDetail", "BatchDetail",
    "OrderDetail", "LaybyDetail", "AccountDetail", "DealDetail",
    "ContactDetail", "LeadDetail", "CaseDetail", "CampaignDetail",
    "WillCallBag", "MessageDetail", "JournalDetail", "InvoiceDetail",
]

#: Pages that are read-only on purpose, and why.
#:
#: This list is the difference between a report people read and one they learn
#: to scroll past. A page that will never have actions, listed as a gap every
#: time the check runs, trains the reader to skip the section — and then the
#: real gap in it goes unread too. Each entry states the reason, so the
#: judgement can be argued with rather than inherited.
READ_ONLY_ON_PURPOSE = {
    "ClaimDetail":
        "a claim is acted on through its batch — submitted, settled and "
        "reversed there — and there is no per-claim endpoint to call",
    "ShiftDetail":
        "a cashed-up shift is a signed document. Editing one after the count "
        "is exactly what the blind count exists to prevent",
    "AccountDetail":
        "a ledger account is changed by posting to it, never by editing the "
        "balance. The chart of accounts is where the account itself is edited",
    "MessageDetail":
        "a message that has been sent cannot be unsent, and one that has not "
        "is managed from the campaign that queued it",
    "ContactDetail":
        "editing lives on the account the contact belongs to, so the "
        "relationship and the person are changed in one place",
}

#: A control in the header, which is where somebody looks for the actions.
# `actions=` anywhere, because `RecordPage` takes it as a prop and the prop
# is rarely on the same line as the tag. The first version required both
# inside one opening tag and reported PatientDetail as having no header
# actions when it passes them — a false absence, and one of those is enough
# for somebody to stop reading the whole report.
HEADER = re.compile(r'page-actions|actions=[{]')
#: Any control that does something at all, header or not.
ACTS = re.compile(
    r'api\.(post|put|patch|delete)\(|<BusyButton|onClick=\{')
MODAL = re.compile(r'useConfirm|useAsk|modal-backdrop|<Confirm|setEditing|setAsking')
#: A handover that carries the record, rather than a bare link to a screen.
CARRIES = re.compile(r'(navigate|to)=?\(?[`"\'][^`"\']*\?[a-z_]+=\$\{')
#: A handover to a work screen that carries nothing.
#:
#: Deliberately NOT a back-link. `<Link to="/pos"><ArrowLeft/> Front Shop` is
#: navigation and carries nothing on purpose; reporting it flags two false
#: positives for every real one, which is how a report stops being read. The
#: first attempt at this excluded them with a lookahead that stopped at the `<`
#: immediately before `ArrowLeft` — so it excluded nothing at all.
BARE = re.compile(
    r'(navigate\(|to=)[`"\']/(pos|dispense)[`"\'](?![^\n]{0,80}ArrowLeft)')


def main() -> int:
    only_gaps = "--gaps" in sys.argv
    print(f"  {'':<22}{'header':<9}{'acts':<7}{'modal':<8}{'hands over':<12}")
    print(f"  {'-' * 58}")

    read_only: list[str] = []
    no_header: list[str] = []
    bare_links: list[str] = []
    seen = 0

    for name in DETAIL:
        path = PAGES / f"{name}.tsx"
        if not path.exists():
            continue
        seen += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        header = bool(HEADER.search(text))
        acts = bool(ACTS.search(text))
        modal = bool(MODAL.search(text))
        carries = bool(CARRIES.search(text))
        bare = bool(BARE.search(text))

        if not acts and name not in READ_ONLY_ON_PURPOSE:
            read_only.append(name)
        elif not header and name not in READ_ONLY_ON_PURPOSE:
            no_header.append(name)
        if bare:
            bare_links.append(name)

        gap = ((not acts or not header) and name not in READ_ONLY_ON_PURPOSE) or bare
        row = (f"  {name:<22}"
               f"{('Y' if header else '·'):<9}"
               f"{('Y' if acts else '·'):<7}"
               f"{('Y' if modal else '·'):<8}"
               f"{('Y' if carries else '· ') + (' (bare link)' if bare else ''):<12}")
        if not only_gaps or gap:
            print(row)

    print()
    print(f"  {seen} detail pages read, "
          f"{len(READ_ONLY_ON_PURPOSE)} read-only on purpose")
    if read_only:
        print(f"\n  read-only — you can look at it and not act on it:")
        for n in read_only:
            print(f"    {n}")
    if "--why" in sys.argv:
        print("\n  read-only on purpose:")
        for n, why in sorted(READ_ONLY_ON_PURPOSE.items()):
            print(f"    {n:<18} {why}")
    if no_header:
        # An observation, not a defect. An action that needs a field beside it
        # — settle *how many*, file it under *which* department — belongs where
        # the field is, and hoisting it into the header would separate the
        # control from the thing it controls. Listed so each one can be
        # checked as deliberate; not called a failure.
        print(f"\n  actions in the body rather than the header. Right where the "
              f"action needs a field beside it, worth a look where it does not:")
        for n in no_header:
            print(f"    {n}")
    if bare_links:
        print(f"\n  hands over without carrying the record — the next screen "
              f"opens empty:")
        for n in bare_links:
            print(f"    {n}")
    # A map, not a gate. A dispensing record must not be editable and a fiscal
    # receipt must not be touched at all, so demanding actions everywhere would
    # be demanding the wrong thing.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
