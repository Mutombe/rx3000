"""Pressing a button that writes something shows that it worked.

THE FAULT, AS IT WAS REPORTED.

"When I settle something awaiting payment and click Take $14.30, it closes as
desired but I'm not seeing the processing of the item in the table. The whole
point is to know what's happening every step of the way."

That screen awaited the request and changed nothing while it was in flight, so
the row sat looking exactly as it had a second earlier. A row that looks
untouched is a row somebody presses again, and on a till that means taking the
money twice.

THREE TIERS, AND A WRITE SHOULD REACH THE TOP ONE.

  the row says it    useOptimisticList for a list whose rows come and go,
                     useRowWork for a button ON a row that changes it in
                     place, closeThenSave for a dialog, useDoing for work
                     that outlives its screen. This is what was asked for.

  the button says it BusyButton holds the promise, disables, spins and swaps
                     its label; or a page does the same by hand with a flag.
                     Real feedback, and most of the product has it. It tells
                     you the BUTTON is working, not what is happening to the
                     ROW, which is the difference somebody scanning a table
                     needs.

  nothing            the screen is unchanged until the server answers.

TWO COUNTS I GOT WRONG, RECORDED HERE BECAUSE THEY WENT INTO COMMITS.

The first version did not know about BusyButton and called a hundred files
silent. Most were not: their buttons spin, and 58 files use it.

The second still called 39 silent, because a page can hand-roll the same
thing — `disabled={busy === "close"}` with the label swapping to "Closing…" —
and 22 files do exactly that. StockTake does it on all four of its actions and
was being reported as saying nothing at all.

A third miss, found while fixing the screens the second count named: four of
them apply the change at once and restore a snapshot if the server refuses,
which is the strongest form of this and exactly what useOptimisticList
packages. GoodsReceiptDetail is one. They are counted with the row now.

The honest figure is 11. A number read out of a guard is worth exactly what
the guard looks at, so this one names every tier it found rather than lumping
everything that is not the newest mechanism into "silent".

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
#: The same thing, written by hand: a flag that disables a control or swaps its
#: label while the request is out. Older than the component and just as real.
FLAG = r"(busy|saving|pending|working|submitting|sending|posting|adding|asking|filing|creating|removing|deleting|closing|settling)"
HAND = re.compile(
    # disabled={busy === "close"} — the control is out of reach while it works
    r"disabled=\{[^}]*" + FLAG
    # busy === "close" ? "Closing…" — the label says what it is doing
    + r"|" + FLAG + r"[^;\n]{0,70}…")

#: The screen changed at once and puts itself back if the server refuses: a
#: snapshot taken before the write and restored in the catch. This is the
#: pattern useOptimisticList packages, written out by hand, and it is the
#: strongest of the lot — GoodsReceiptDetail and three others do it.
ROLLBACK = re.compile(
    # const was = …        the state before the write is kept,
    r'const (was|before|previous|snapshot|prior)\b'
    # … catch { … was … }  and put back when the server refuses.
    r'[\s\S]{0,2000}?catch[\s\S]{0,400}?\1\b')

#: Writes that SHOULD block, with the reason. Not skipped quietly.
MUST_WAIT = {
    "pages/Login.tsx": "signing in has nothing on screen to be optimistic about",
    "pages/Register.tsx": "an account that claims to exist before it does is a lie with consequences",
}

#: Writes that are deliberately invisible, with the reason each one is. These
#: are not oversights: showing them would be the fault.
QUIET = {
    "components/ScriptTotals.tsx":
        "a pricing figure that cannot be worked out must not stop anybody "
        "dispensing, so it simply does not appear",
    "components/LabelSheet.tsx":
        "recording that a label was reprinted must never delay the label; "
        "a failure warns afterwards and the sticker still goes on the box",
}

#: What the sweep has reached. It comes down as screens are done; a rise means
#: a new screen was written that writes without saying so.
CEILING = 5


def main() -> int:
    silent = []
    button_only = []
    by_hand = []
    total = 0
    for path in sorted(SRC.rglob("*.tsx")):
        name = path.relative_to(SRC).as_posix()
        text = path.read_text(encoding="utf-8")
        writes = len(WRITES.findall(text))
        if not writes or name in MUST_WAIT or name in QUIET:
            continue
        total += 1
        if any(h in text for h in ROW):
            continue
        if any(h in text for h in BUTTON):
            button_only.append((writes, name))
            continue
        if ROLLBACK.search(text):
            continue
        if HAND.search(text):
            by_hand.append((writes, name))
            continue
        silent.append((writes, name))

    silent.sort(reverse=True)
    button_only.sort(reverse=True)
    by_hand.sort(reverse=True)
    print(f"\n{total} files write.\n"
          f"  {len(button_only):>3} say so on the button (BusyButton)\n"
          f"  {len(by_hand):>3} say so on the button, written by hand\n"
          f"  {len(silent):>3} say nothing at all (ceiling {CEILING})\n")
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
