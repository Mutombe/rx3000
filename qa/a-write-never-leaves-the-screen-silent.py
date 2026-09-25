"""Pressing a button that writes something shows that it worked.

THE FAULT, AS IT WAS REPORTED.

"When I settle something awaiting payment and click Take $14.30, it closes as
desired but I'm not seeing the processing of the item in the table. The whole
point is to know what's happening every step of the way."

That screen awaited the request and changed nothing while it was in flight, so
the row sat looking exactly as it had a second earlier. A row that looks
untouched is a row somebody presses again, and on a till that means taking the
money twice.

TWO TIERS, AND A WRITE SHOULD REACH THE SECOND.

  BusyButton          the button itself disables, spins and changes its label
                      while it holds the promise. This is the floor: it is
                      real feedback, and 88 files already have it. It is not
                      the thing that was asked for, because it tells you the
                      BUTTON is working and not what is happening to the ROW.

  useOptimisticList   a list whose rows are created, edited and removed.
  useRowWork          a button ON a row that changes that row in place.
  closeThenSave       a dialog that writes and should close on the keystroke.
  useDoing            a job that outlives the screen that started it.

A COUNT I GOT WRONG, RECORDED HERE.

The first version of this check did not know about BusyButton and reported a
hundred files as giving "no sign at all". Most of them were not silent; their
buttons spin. The honest figure is the one below: silent, and then separately
the ones whose only feedback is the button.

This counts files that write and reach for none of them. It is a file-level
check: a file with six writes and one optimistic path is not something a
regular expression can judge, and a check that guessed at it would report
faults that are not there.

DELIBERATELY NOT EVERY WRITE.

Signing in should wait — there is nothing on screen to be optimistic about,
and a login that claims to have worked before it has is a lie with
consequences. Same for anything that must be certain before the screen moves
on. Those are listed by name below rather than silently skipped, so the
exception is visible and arguable.

Run by exit code, with a ceiling: the number may fall, never rise.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

WRITES = re.compile(r"\bapi\.(post|put|patch|delete)\b")
#: The row or the list says something.
ROW = ("useOptimisticList", "useRowWork", "closeThenSave", "useDoing", "rowClass(")
#: The button says something. Real, but about the button.
BUTTON = ("BusyButton",)

#: Writes that SHOULD block, with the reason. Not skipped quietly.
MUST_WAIT = {
    "pages/Login.tsx": "signing in has nothing on screen to be optimistic about",
    "pages/Register.tsx": "an account that claims to exist before it does is a lie with consequences",
}

#: What the sweep has reached. It comes down as screens are done; a rise means
#: a new screen was written that writes without saying so.
CEILING = 39


def main() -> int:
    silent = []
    button_only = []
    total = 0
    for path in sorted(SRC.rglob("*.tsx")):
        name = path.relative_to(SRC).as_posix()
        text = path.read_text(encoding="utf-8")
        writes = len(WRITES.findall(text))
        if not writes or name in MUST_WAIT:
            continue
        total += 1
        if any(h in text for h in ROW):
            continue
        if any(h in text for h in BUTTON):
            button_only.append((writes, name))
            continue
        silent.append((writes, name))

    silent.sort(reverse=True)
    button_only.sort(reverse=True)
    print(f"\n{total} files write. {len(button_only)} say so on the button "
          f"only; {len(silent)} say nothing at all (ceiling {CEILING}).\n")
    for writes, name in silent[:15]:
        print(f"    {writes:>2} write(s)  {name}")
    if len(silent) > 15:
        print(f"    … and {len(silent) - 15} more")

    if len(silent) > CEILING:
        print(f"\n  That is more than there were. A new screen writes without "
              f"saying so.\n  Reach for useRowWork for a button on a row, "
              f"closeThenSave for a dialog,\n  useOptimisticList for a list, "
              f"or useDoing for work that outlives the screen.")
        return 1
    if len(silent) < CEILING:
        print(f"\n  Fewer than the ceiling of {CEILING}. Lower CEILING to "
              f"{len(silent)} so it cannot climb back.")
        return 1
    print("\n  Held at the ceiling. Every one of these is a screen where "
          "pressing a\n  button that writes shows nothing until the server "
          "answers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
