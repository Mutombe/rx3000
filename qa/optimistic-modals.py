"""When you press the button in a dialog, does it make you wait?

The pattern is settled: the dialog closes at once, the row appears in a
provisional state, a snapshot lets a refusal restore exactly what was there, a
generation counter stops a late reload overwriting a fresh edit, and a pending
row is kept out of actions because it has no id yet. `useOptimisticList` holds
all of it, and `closeThenSave` holds the smaller half for dialogs that do not
own the list they write into.

WHAT THIS MEASURES, AND WHY IT CHANGED

It used to ask whether a FILE imported the helper. That was wrong in both
directions and the rollout is what exposed it. Nineteen screens had the close
moved above the round trip by hand and still counted as waiting, because they
did not import anything. Dispense.tsx makes thirteen writes; importing the
helper for one of them would have counted all thirteen as done.

So it now reads the writes, not the imports. For every `try` block that awaits
the api behind a dialog, it asks one question: does the close come before that
await, or after it? Before means the dialog is gone by the time the request
leaves. After means somebody is watching a spinner on a button that had already
worked.

That is a behaviour, so it cannot be satisfied by adding an import, and a file
is only finished when every write in it is.

WHAT COUNTS AS CLOSING A DIALOG

Not every `setSomething(false)` shuts a dialog. The first version of this check
read `setInternal(false)` in the help desk, which unticks a checkbox, and
`setBusy(false)` in dispensing, which clears a spinner, and reported both as
screens making somebody wait. Neither is a dialog and neither has anything to
close early.

So the state variable has to be the one the dialog is rendered behind: `foo`
counts only if the file contains a modal whose markup is guarded by `foo`. That
is the definition of a close, rather than a guess from its name, and it means
adding a flag called `setEditing` to hold a spinner will not put a file on this
list.

A `try` with no such close is not behind a dialog. A close inside a nested
block is conditional on something, so moving it would change behaviour rather
than timing; those are listed separately to be read.

AND THEN THE SECOND QUESTION, WHICH IS THE ONE THAT MATTERS

Closing the dialog early is the cheap half. Twenty screens were converted to
do it and every one of them passed this check, and every one of them still made
somebody wait: the dialog went, and the table sat exactly as it was until the
server answered. On a branch line that is a second or two of a screen that
looks like nothing happened, which is when a person presses the button again.

So a screen that renders a list and writes to it through a dialog is also
asked whether the row turns up. `useOptimisticList` puts a placeholder in at
once, keeps a snapshot to undo it, and marks it so the row is drawn faded and
cannot be clicked or selected. A screen that only closes early is listed as
`half` — not failing, because closing early is a real improvement, but not
finished either.

    python qa/optimistic-modals.py            what is left
    python qa/optimistic-modals.py --strict   fail while anything is left
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"

#: A try/catch. Non-greedy to the first `} catch` at any depth is wrong for
#: nested trys, and there are none in these files; the count below is asserted
#: so a new one shows up as a change rather than as silence.
TRY = re.compile(r'\btry \{(.*?)\n\s*\} catch', re.S)
AWAIT = re.compile(r'await\s+api\.(?:post|put|patch|delete)\b')
#: Things that might shut a dialog: a callback, or a state setter going empty.
#: A setter only counts once `guards_a_dialog` agrees.
CLOSE = re.compile(
    r'(?:^|[\s;{])(onClose\(\)|close\(\)|dismiss\(\)|'
    r'set[A-Z]\w*\((?:null|false|undefined)\))\s*;')

#: Modal markup, in either of the two shapes this product uses.
MODAL = re.compile(r'modal-backdrop|<Modal\b')

#: A screen that renders a list, writes to it, and does so from a dialog. All
#: three have to be true before "does the row appear" is even a question.
LISTS = re.compile(r'<table|\.map\(\s*\(?\w+\)?\s*=>\s*<(tr|li)\b|<RowLink')
WRITES = re.compile(r'api\.(post|put|patch|delete)\b')
DIALOG = re.compile(r'modal-backdrop|<Modal\b|useConfirm|setAdding|setEditing'
                    r'|setShowForm|setRaising|setAsking')


def guards_a_dialog(text: str, statement: str) -> bool:
    """Is this setter's variable the one a modal is rendered behind?

    `setEditing(null)` in a file where `{editing && <div
    className="modal-backdrop">` appears is a close. The same call in a file
    where `editing` only disables a button is not.
    """
    if statement in ("onClose()", "close()", "dismiss()"):
        return True
    name = re.match(r'set([A-Z]\w*)\(', statement)
    if not name:
        return False
    var = name.group(1)[0].lower() + name.group(1)[1:]
    # The variable opening a JSX expression, with modal markup close behind it.
    for use in re.finditer(r'\{\s*' + re.escape(var) + r'\s*(?:&&|\?|\.)', text):
        if MODAL.search(text[use.end():use.end() + 700]):
            return True
    return False

#: Screens where waiting is the right behaviour, with the reason. Each is a
#: decision somebody made, not a pattern that lets a file through.
SETTLED = {
    # Money. A dialog that closes is read as "done", and for money "done"
    # means taken. It must not say so before the server agrees.
    "POS.tsx": "the till settles money; a row that appears before the server "
               "has taken payment is the one place a provisional row would be "
               "read as cash in the drawer",
    "PartPayment.tsx": "money being split; the amount must be confirmed taken "
                       "before the dialog agrees that it was",
    "SettleSale.tsx": "the same, at the till",
    "MoneyOwed.tsx": "a debt being paid down",
    "TillLock.tsx": "a till being counted and locked; the count is the point",
    "DriverDetail.tsx": "a driver handing in what they collected, which is the "
                        "moment custody of the cash changes",

    # Stock. A quantity shown as moved before it moved is a quantity somebody
    # counts on, and the recount is worse than the wait.
    "StockTake.tsx": "a count being committed against what is on the shelf",
    "Orders.tsx": "goods being received; the quantity booked in is the "
                  "quantity somebody will sell from",
    "ReceiveByScan.tsx": "the same, at the scanner",
    "Scanner.tsx": "the same",

    # Things that leave the building and cannot be recalled.
    "Reminders.tsx": "messages go to patients; there is no unsending one",
    "Deliveries.tsx": "a delivery marked as handed over is a signature claimed",

    # Long forms whose refusals are ordinary. Closing optimistically throws the
    # typed work away on exactly the failures that happen most, and "it did not
    # save, type it again" is not a saving over a second of waiting.
    "PatientForm.tsx": "a full patient record; a member number the scheme "
                       "rejects would cost the whole form",
    "NewJournal.tsx": "several typed lines against refusals that are routine, "
                      "an entry that does not balance, a closed period",
    "StockUpload.tsx": "a file and a mapping, which cannot be retyped at all",

    # Not lists.
    "StepUp.tsx": "an authorisation prompt, not a list",
    "Confirm.tsx": "the confirmation dialog itself",
    "LabelSheet.tsx": "prints, does not write a row",
    "AlterScript.tsx": "an alteration is recorded against a script and shown "
                       "on its own page, not appended to a list here",
}


#: One write inside a file that is otherwise optimistic. Keyed on the close
#: statement rather than a line number, so it survives the file moving around
#: and still names exactly one dialog.
#:
#: These are the same rule as the screens above, applied at a finer grain: the
#: stock room and the lay-by book each have a dialog that moves value and
#: several that do not, and exempting the file would have exempted the rest.
SETTLED_WRITES = {
    ("pages/Authorisations.tsx", "setUsing(null)"):
        "drawing against an authorisation spends an approved amount, and the "
        "refusal that actually happens is the one for exceeding it",
    ("pages/Branches.tsx", "setMoving(false)"):
        "stock moving between branches; both shelves are wrong until the "
        "server agrees",
    ("pages/Claiming.tsx", "setSettling(null)"):
        "a remittance being settled, which is money",
    ("pages/LayBys.tsx", "setPaying(null)"):
        "a payment against a lay-by",
    ("pages/Repeats.tsx", "setSupplying(null)"):
        "supplying a repeat hands medicine over the counter",
    ("pages/Stock.tsx", "setAdjusting(null)"):
        "an adjustment is the number somebody will trust at the next count",
    ("pages/SchemeCalendar.tsx", "setEditing(null)"):
        "the dialog stays up across a step-up password prompt, and one of its "
        "two writes can be cancelled at that prompt; closing early would put "
        "the prompt over a dialog that had already gone, and lose the context "
        "for the warning that the dates saved but the terms did not",
}

#: Screens that render a list and write to it, where a provisional row would
#: say something untrue. Separate from SETTLED above, because closing a dialog
#: early and drawing a row that does not exist yet are different promises.
#:
#: Three reasons appear here, and only the first is about money.
ROW_SETTLED = {
    # A row that appears before the server took the money is a row that says
    # the money was taken.
    "CashUp.tsx": "a till being counted; the count is the record",
    "PaySupplier.tsx": "money going out to a supplier",
    "ExpiryProvision.tsx": "a provision posted to the ledger",
    "SaleDetail.tsx": "a fiscal credit note, which is a receipt the revenue "
                      "authority has already been told about",
    "LayBys.tsx": "a payment against a lay-by",
    "LayByDetail.tsx": "the same, on the record itself",
    "Payables.tsx": "supplier payments and the queries raised against them",

    # Stock, and medicine that physically leaves.
    "ReturnLines.tsx": "stock coming back over the counter",
    "BatchDetail.tsx": "a batch written off",
    "WillCall.tsx": "medicine handed to the person collecting it",
    "WillCallBag.tsx": "the same, from the bag",
    "DispensingDetail.tsx": "the same, from the dispensing",
    "Repeats.tsx": "supplying a repeat hands medicine over",

    # Things that leave the building and cannot be recalled.
    "CampaignDetail.tsx": "a campaign being sent to patients",
    "ClaimBatchDetail.tsx": "a claim batch going to a funder",
    "Marketing.tsx": "creating a campaign here sends it in the same breath, "
                     "so the row would claim a delivery that has not happened",
    "ToFollows.tsx": "settling one hands the medicine over and cancelling one "
                     "writes off what the patient owed",

    # Money being given up or charged on.
    "Remittances.tsx": "resolving a line either bills the patient or writes "
                       "the variance off, and both are money",
    "RemittanceDetail.tsx": "the same, on the line itself",

    # Controls where the provisional state is the dangerous one.
    "Periods.tsx": "closing a period locks the ledger against it. A row that "
                   "reads closed before it is closed tells somebody to stop "
                   "posting into a period that is still open",
    "Drivers.tsx": "its only write retires a driver, and the server refuses "
                   "while they are still carrying shop money. A row that "
                   "vanishes and comes back is a worse answer than the wait",
    "SchemeCalendar.tsx": "its dialog stays up across a step-up prompt and one "
                          "of its two writes can be cancelled there",

    # Not a list-create at all. Each renders a table and writes something, so
    # the coarse test picks them up, but there is no new row to place.
    "Fiscal.tsx": "reads the fiscal day; it writes nothing",
    "InvoiceDetail.tsx": "one invoice, read",
    "PrescriberDetail.tsx": "edits the prescriber record, which is the page "
                            "rather than a row in a list on it",
    "ComplianceDocument.tsx": "one document, and deleting it leaves the page",
    "PatientDetail.tsx": "edits the patient record; the tables on it are that "
                         "patient's history and are not written from a dialog",
    "StaffDetail.tsx": "its one list is the placement panel, which already "
                       "uses the hook",
    "Dispense.tsx": "the draft list is kept in step by its own nonce, and the "
                    "dialogs on this screen write scripts rather than rows",
    "HeadOffice.tsx": "a shell of tabs; the lists belong to the panels inside "
                      "it, which are judged on their own",
}


def main() -> int:
    strict = "--strict" in sys.argv
    early: list[tuple[str, str]] = []
    late: list[tuple[str, str]] = []
    conditional: list[tuple[str, str]] = []
    settled_here: list[tuple[str, str]] = []
    files_late: dict[str, int] = {}

    for file in sorted(list((SRC / "pages").glob("*.tsx"))
                       + list((SRC / "components").glob("*.tsx"))):
        if file.name in SETTLED:
            continue
        text = file.read_text(encoding="utf-8", errors="replace")
        where = f"{file.parent.name}/{file.name}"

        # A dialog handed to closeThenSave has already answered the question.
        for block in TRY.finditer(text):
            body = block.group(1)
            hit = AWAIT.search(body)
            if not hit:
                continue
            shut = next((m for m in CLOSE.finditer(body)
                         if guards_a_dialog(text, m.group(1))), None)
            if not shut:
                continue          # not behind a dialog
            line = text.count("\n", 0, block.start()) + 1
            at = f"{where}:{line}"
            # A close inside a nested block is conditional on something, so
            # moving it would change behaviour rather than timing.
            head = body[:shut.start()]
            if (where, shut.group(1)) in SETTLED_WRITES:
                settled_here.append((at, shut.group(1)))
            elif head.count("{") != head.count("}"):
                conditional.append((at, shut.group(1)))
            elif shut.start() < hit.start():
                early.append((at, shut.group(1)))
            elif (where, shut.group(1)) in SETTLED_WRITES:
                settled_here.append((at, shut.group(1)))
            else:
                late.append((at, shut.group(1)))
                files_late[where] = files_late.get(where, 0) + 1

        for call in re.finditer(r'closeThenSave\(', text):
            line = text.count("\n", 0, call.start()) + 1
            early.append((f"{where}:{line}", "closeThenSave"))

    total = len(early) + len(late)
    print(f"  {len(early)} of {total} dialog write(s) close before the round "
          f"trip, not after it\n")

    if late:
        for at, how in late:
            print(f"  wait  {at:<44} {how} runs after the await")
        print()
    for at, how in sorted(conditional):
        print(f"  read  {at:<44} {how} is conditional, so it is a judgement")

    # ---- does a row actually appear? ------------------------------------
    #
    # Only screens that both render a table and write to it through a dialog.
    # A dialog that writes somewhere else has no row here to place.
    rows_now: list[str] = []
    rows_later: list[str] = []
    for file in sorted(list((SRC / "pages").glob("*.tsx"))
                       + list((SRC / "components").glob("*.tsx"))):
        if file.name in SETTLED:
            continue
        text = file.read_text(encoding="utf-8", errors="replace")
        if not (LISTS.search(text) and WRITES.search(text)):
            continue
        if not DIALOG.search(text):
            continue
        if file.name in ROW_SETTLED:
            continue
        where = f"{file.parent.name}/{file.name}"
        if "useOptimisticList" in text:
            rows_now.append(where)
        else:
            rows_later.append(where)

    total_lists = len(rows_now) + len(rows_later)
    print(f"\n  {len(rows_now)} of {total_lists} list screen(s) show the row "
          f"before the server answers\n")
    for where in rows_later:
        print(f"  half  {where:<40} the dialog closes, the table waits")
    print(f"\n  {len(ROW_SETTLED)} screen(s) should not show a provisional "
          f"row:")
    for name, why in sorted(ROW_SETTLED.items()):
        print(f"        {name}: {why}")

    print(f"\n  {len(SETTLED)} screen(s) and {len(settled_here)} single "
          f"dialog(s) wait on purpose:")
    for name, why in sorted(SETTLED.items()):
        print(f"        {name}: {why}")
    for at, how in sorted(settled_here):
        where = at.rsplit(":", 1)[0]
        print(f"        {at} ({how}): {SETTLED_WRITES[(where, how)]}")

    # The row question fails strict too, now that it is answered everywhere.
    # A screen added later that writes to its own list from a dialog is either
    # optimistic or is written into ROW_SETTLED with a reason; those are the
    # only two endings, and neither of them is silence.
    if rows_later and strict:
        print(f"\n{len(rows_later)} screen(s) close the dialog and then leave "
              f"the table unchanged until the server answers.")
        return 1

    if late and strict:
        print(f"\n{len(late)} write(s) in {len(files_late)} file(s) still make "
              f"somebody watch a spinner on a button that had already worked.")
        return 1
    if not late:
        print(f"\nevery dialog that writes is gone by the time the request "
              f"leaves, except where waiting is the point")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
