"""Which screens still make you wait for their own bookkeeping?

`useOptimisticList` exists, is complete, and implements the whole pattern: the
dialog closes at once, the row appears in a provisional state, a snapshot is
taken so a refusal restores exactly what was there, a generation counter stops
a late reload overwriting a fresh edit, and a pending row is kept out of
actions because it has no id yet.

It was written and then applied to four screens. Everywhere else a modal still
holds itself open across the round trip and the list is re-fetched afterwards,
so pressing a button that plainly worked is followed by waiting to see it.

This lists what is left, so the remainder is a backlog somebody can see rather
than a claim that the pattern is "in the product".

HOW A SCREEN IS JUDGED

It is a candidate if it both renders a list and writes through a dialog: a
table or a list, and a POST, PUT or DELETE that is followed by a re-read. A
screen that only reads, or only writes without a list to update, has nothing to
be optimistic about.

It counts as converted if it imports `useOptimisticList`. That is a coarse
test, and deliberately so: a finer one would be a rule to satisfy rather than a
question to answer.

    python qa/optimistic-modals.py            what is left
    python qa/optimistic-modals.py --strict   fail while anything is left
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"

WRITES = re.compile(r'api\.(post|put|patch|delete)\b')
RELOADS = re.compile(r'\b(load|reload|refresh|loadList|load\w*)\(\)')
LISTS = re.compile(r'<table|\.map\(\s*\(?\w+\)?\s*=>\s*<(tr|li)\b|<RowLink')
DIALOG = re.compile(r'modal-backdrop|<Modal\b|useConfirm|setAdding|setEditing|setShowForm')

#: Screens with a list and a write that are deliberately not optimistic, with
#: the reason. Each is a decision, not an exemption.
SETTLED = {
    "POS.tsx": "the till settles money; a row that appears before the server "
               "has taken payment is the one place a provisional row would be "
               "read as cash in the drawer",
    "StepUp.tsx": "an authorisation prompt, not a list",
    "Confirm.tsx": "the confirmation dialog itself",
    "LabelSheet.tsx": "prints, does not write a row",
    "AlterScript.tsx": "an alteration is recorded against a script and shown "
                       "on its own page, not appended to a list here",

    # Long forms whose refusals are ordinary. Closing optimistically throws the
    # typed work away on exactly the failures that happen most, and "it did not
    # save, type it again" is not a saving over a second of waiting. The rule
    # that separates them: how much was typed, and how likely a refusal is.
    "PatientForm.tsx": "a full patient record; a member number the scheme "
                       "rejects would cost the whole form",
    "NewJournal.tsx": "several typed lines against refusals that are routine — "
                      "an entry that does not balance, a closed period",
    "StockUpload.tsx": "a file and a mapping, which cannot be retyped at all",
    "PartPayment.tsx": "money being split; the amount must be confirmed taken "
                       "before the dialog agrees that it was",
    "SettleSale.tsx": "the same, at the till",
}


def main() -> int:
    strict = "--strict" in sys.argv
    done, todo = [], []

    for file in sorted(list((SRC / "pages").glob("*.tsx"))
                       + list((SRC / "components").glob("*.tsx"))):
        text = file.read_text(encoding="utf-8", errors="replace")
        if not (WRITES.search(text) and LISTS.search(text) and DIALOG.search(text)):
            continue
        if file.name in SETTLED:
            continue
        where = f"{file.parent.name}/{file.name}"
        if "useOptimisticList" in text or "closeThenSave" in text:
            done.append(where)
        else:
            # How many writes it makes, as a rough size for the conversion.
            todo.append((where, len(WRITES.findall(text))))

    total = len(done) + len(todo)
    print(f"  {len(done)} of {total} screens with a list and a dialog are "
          f"optimistic\n")
    for where in done:
        print(f"  ok    {where}")
    if todo:
        print()
        for where, writes in sorted(todo, key=lambda r: -r[1]):
            print(f"  wait  {where:<38} {writes} write(s) still close after "
                  f"the round trip")

    print(f"\n  {len(SETTLED)} screen(s) deliberately not optimistic:")
    for name, why in sorted(SETTLED.items()):
        print(f"        {name}: {why}")

    if todo and strict:
        print(f"\n{len(todo)} screen(s) still make somebody wait for a write "
              f"that had already succeeded.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
