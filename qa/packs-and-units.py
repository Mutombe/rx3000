"""A pack price multiplied by a count of units, found in the source.

    python qa/packs-and-units.py
    python qa/packs-and-units.py --all      # including the allowed ones

`Product.cost_price` is what one PACK cost and `unit_price` is what one PACK
sells for. `quantity_on_hand`, `reorder_level`, `reorder_quantity`,
`max_level`, `Dispensing.quantity` and every `StockBatch` quantity count
DISPENSABLE UNITS: a tub of a thousand capsules is a thousand.

Multiply one by the other and the answer is wrong by the pack size.

WHY THIS IS WORTH A CHECK OF ITS OWN

Because it is invisible. The expression `product.cost_price *
product.quantity_on_hand` reads like it is already correct, the number it
produces is plausible, and every screen that makes the same mistake agrees
with every other screen, so nothing looks broken anywhere.

It was in twenty two places at once. This pharmacy's shelf is worth 377,357.90
at cost and the system reported 13,380,343.88; the stock valuation screen put
the retail figure at 629,121,282,766.43, which is six hundred and twenty nine
billion, for a pharmacy in Harare. The over the counter sale charged a whole
box for every tablet handed over. A product page showed a margin of minus
seven hundred and four per cent, next to another that read a sensible forty
one, with nothing to say which was which.

It was found by asking the pharmacy's own export what IT thought the stock was
worth, not by reading the code. That is not a thing to rely on twice.

WHAT COUNTS

`cost_price` or `unit_price` on one side of a `*`, anywhere under backend/app.

WHAT DOES NOT

A line that says which unit it means, by carrying `# units ok:` and a reason. A
purchase order line and a supplier invoice really are counted in packs, and
the till really does sell boxes, so those multiplications are right and have
to stay. The comment is the point: it makes the author answer the question
once, in writing, where the next reader can see the answer.

`services/valuation.py` is where the rule lives and is skipped. Seeds and
importers write their own fixtures and are skipped too.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "backend" / "app"

#: Where the rule is defined, and files that build their own fixtures.
#: valuation.py is where the rule lives. migrate.py compares prices to
#: repair them rather than valuing anything. The rest write fixtures.
SKIP_FILES = {"valuation.py", "migrate.py", "realseed.py", "seed.py",
              "demoseed.py"}
SKIP_DIRS = {"importers", "__pycache__"}

#: `x * something.cost_price` or `something.unit_price * x`, on one line.
PRICED = re.compile(r"(cost_price|unit_price)\s*\*|\*\s*[^*\n]{0,40}?(cost_price|unit_price)")

#: The author has said which unit this is, and why.
ALLOWED = re.compile(r"#\s*units ok:", re.I)

#: The accessors that already divide. Naming one IS the answer.
SETTLED = re.compile(r"\b(unit_cost\(\)|per_unit\(\)|valuation\.|packs_at_cost)")


def offenders(show_all: bool) -> tuple[list, list]:
    bad: list[tuple[str, int, str]] = []
    allowed: list[tuple[str, int, str]] = []
    for path in sorted(APP.rglob("*.py")):
        if path.name in SKIP_FILES or SKIP_DIRS & set(path.parts):
            continue
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        for number, line in enumerate(lines, 1):
            if not PRICED.search(line) or SETTLED.search(line):
                continue
            # The justification may sit on the line or just above it, because
            # a long expression is usually wrapped.
            near = "\n".join(lines[max(0, number - 6):number])
            rel = path.relative_to(ROOT).as_posix()
            (allowed if ALLOWED.search(near) else bad).append(
                (rel, number, line.strip()))
    return bad, allowed


def main() -> int:
    show_all = "--all" in sys.argv
    bad, allowed = offenders(show_all)

    if bad:
        print("A PACK price multiplied by something that may be UNITS\n")
        for rel, number, src in bad:
            print(f"  {rel}:{number}")
            print(f"      {src[:110]}")
        print("\n  Use services/valuation (at_cost / at_retail), or the model's")
        print("  unit_cost() / per_unit(). If the quantity really is packs, say")
        print("  so on the line with `# units ok: <why>`.\n")

    if allowed and show_all:
        print("Said to be packs, with a reason\n")
        for rel, number, src in allowed:
            print(f"  {rel}:{number}  {src[:90]}")
        print()

    print(f"{len(bad)} unexplained · {len(allowed)} declared sound")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
