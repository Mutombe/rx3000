"""Does the shorthand expand into something safe to print on a box?

The codes are typed by a dispenser and the sentence is read by a patient at
home. Those are two different people and only one of them is in the room, which
is why this file tests the *output*, not the table.

WHAT IT LOOKS FOR

  A code that cannot be typed. `od_eye` and `os_eye` were seeded to dodge the
  `od` collision — `od` being once-daily here and the right eye in the
  ophthalmic literature. Nobody has ever put an underscore in a directions
  field at speed, so the collision was not resolved, only hidden behind a code
  that could never fire.

  A number that does not agree with its noun. `ii tab tds` printed "TWO tablet
  three times a day". A label with a grammatical error in it reads as a label
  nobody checked, and a patient entitled to wonder about the words is entitled
  to wonder about the tablets.

  A code that expands to something already containing a count, so a numeral in
  front of it doubles up. `gtt` meant "instill ONE drop", so `gtt ii` printed
  "instill ONE drop TWO".

  Two codes with the same spelling as an ordinary English word in a position
  where the field also accepts ordinary English — because unknown words pass
  straight through, and that is the property that makes the field safe.

  The `instil` / `instill` spelling, which the inspecting pharmacist raised.
  Both are defensible English; pharmacy labelling uses the double `l`, and a
  label is not the place to be interesting about orthography.

Nothing is committed.

    python qa/sig-codes.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from app.database import SessionLocal              # noqa: E402
from app import tenancy                            # noqa: E402
from app.services import sig                       # noqa: E402

#: shorthand a dispenser would really type -> what the box must read
CASES: list[tuple[str, str]] = [
    ("1t tds pc", "Take ONE tablet three times a day after food."),
    ("2t bd pc", "Take TWO tablets twice a day after food."),
    ("ii tab tds pc", "TWO tablets three times a day after food."),
    ("iii caps od mane", "THREE capsules once a day in the morning."),
    ("i tab nocte", "ONE tablet at night."),
    ("ii gtt b-eye bd", "TWO drops into BOTH eyes twice a day."),
    ("i gtt l-eye qds", "ONE drop into the LEFT eye four times a day."),
    ("1d bd r-eye", "Instill ONE drop twice a day into the RIGHT eye."),
    ("5ml tds pc", "Take 5ml (one medicine spoon) three times a day after food."),
    # Ordinary English passes through untouched, which is what makes the field
    # safe to use for anything the book does not cover.
    ("1t tds pc with water",
     "Take ONE tablet three times a day after food with water."),
    ("One tablet at night", "One tablet at night."),
]


def main() -> int:
    tenancy.set_current_pharmacy(1)
    db = SessionLocal()
    tenancy.stamp(db)
    failures: list[str] = []

    def check(ok: bool, said: str, why: str = "") -> None:
        print(f"  {'ok  ' if ok else 'FAIL'} {said}")
        if not ok:
            failures.append(why or said)

    try:
        sig.seed_if_empty(db)
        sig.refresh(db)
        book = sig.book(db)
        codes = [c for g in book["groups"].values() for c in g]

        print(f"  {book['count']} codes in "
              f"{len(book['groups'])} groups\n")

        for shorthand, expected in CASES:
            got = sig.expand(db, shorthand)
            check(got == expected, f"{shorthand:<24} -> {got}",
                  f"`{shorthand}` prints \"{got}\", not \"{expected}\"")

        print()
        # Every code has to be reachable from a keyboard at speed.
        untypable = [c["code"] for c in codes
                     if "_" in c["code"] or c["code"] != c["code"].strip()]
        check(not untypable,
              "every code can be typed into a directions field",
              f"unreachable codes are still offered: {untypable} — a code with "
              f"an underscore is never typed, so the ambiguity it was invented "
              f"to dodge is still there")

        # A quantity code must not carry a count if a numeral can precede it.
        doubled = [c["code"] for c in codes
                   if c["code"] in {"gtt", "gtts", "tab", "caps"}
                   and any(w in c["expansion"] for w in ("ONE", "TWO", "THREE"))]
        check(not doubled,
              "bare nouns carry no count of their own",
              f"{doubled} expand with a number in them, so `ii {doubled[:1]}` "
              f"would print two counts" if doubled else "")

        # The spelling the inspection raised.
        instil = [c["code"] for c in codes
                  if "instil " in c["expansion"] or c["expansion"].endswith("instil")]
        check(not instil, "\"instill\" is spelt with two l's",
              f"{instil} still print \"instil\"")

        # Plurals, on every countable noun the book can produce.
        for one, many in (("1t", "2t"), ("1c", "2c")):
            plural = sig.expand(db, f"{many} od")
            check(plural.rstrip(".").endswith("once a day")
                  and ("tablets" in plural or "capsules" in plural),
                  f"{many} pluralises: {plural}",
                  f"`{many}` prints \"{plural}\"")

        # And a caution wherever a code is genuinely read two ways.
        flagged = {c["code"] for c in codes if c["caution"]}
        for code in ("od", "hs", "prn"):
            check(code in flagged,
                  f"`{code}` carries a caution",
                  f"`{code}` is read two ways and says nothing about it")
    finally:
        db.rollback()
        db.close()

    print()
    if failures:
        for f in failures:
            print(f"  {f}")
        return 1
    print("the shorthand expands into sentences that can go on a box")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
