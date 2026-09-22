"""The example file the upload screen hands out must actually load.

WHY THIS GUARD EXISTS

An example file is a promise: send one shaped like this and it will work. A
template whose headings the parser no longer recognises is worse than none at
all, because the pharmacy trusts it, sends four thousand rows, and every one
is refused for having nothing that identifies a product.

The headings and the alias map live in one module for that reason, and this
checks the other half: that the file as generated parses and maps every column
it declares. What it deliberately does NOT check is the plan, which needs a
database and a tenant: whether those rows come back as "create" depends on
what that pharmacy already stocks, and a guard that needed a particular
catalogue to pass would be testing the fixture rather than the template.
"""
import sys, pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "backend"))

from app.services import stock_upload as up  # noqa: E402

passed = failed = 0


def check(said, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  ok   {said}")
    else:
        failed += 1
        print(f"  X    {said}")
        if detail:
            print(f"       {detail}")


print("\n  the example file the upload screen hands out\n")

text = up.example_csv()
check("is generated at all", bool(text.strip()))

# Every heading is one the parser knows. This is the drift the guard is for.
unknown = [h for h, _, _ in up.EXAMPLE_COLUMNS if h not in up.ALIASES]
check("uses only headings the parser understands", not unknown,
      f"not in ALIASES: {unknown}")

rows, mapping = up.read(text)
check("parses into rows", len(rows) == 2, f"got {len(rows)}")
check("maps every column it declares",
      len(mapping) == len(up.EXAMPLE_COLUMNS),
      f"declared {len(up.EXAMPLE_COLUMNS)}, mapped {len(mapping)}")

# The columns that turn a catalogue into a delivery. Left out of the example,
# a pharmacy loads its whole range with no stock against any of it.
for wanted in ("quantity", "batch", "expiry", "cost", "price"):
    check(f"carries a {wanted} column",
          wanted in mapping.values(),
          f"mapped: {sorted(set(mapping.values()))}")

# The second row leaves the receiving columns empty on purpose: a file may be
# a catalogue entry with nothing received against it.
blanks = [h for h, _, third in up.EXAMPLE_COLUMNS if third == ""]
check("shows that columns may be left empty", bool(blanks),
      "every cell of the second row is filled, so nothing demonstrates it")

# NO IDENTIFIER IN A TEMPLATE MAY BE A PLAUSIBLE ONE.
#
# The first draft carried the NAPPI code 702114, which is real: previewing the
# example came back "update Ibuprofen 400mg", so a template downloaded, half
# filled in and sent would have rewritten the price of a line already on the
# shelf. A code in an example has to be one that cannot match anything.
IDENTIFYING = {"barcode", "nappi_code", "stock_code"}
risky = [
    (h, first, third) for h, first, third in up.EXAMPLE_COLUMNS
    if h in IDENTIFYING
    for cell in (first, third)
    if cell and not cell.upper().startswith("EXAMPLE")
]
check("uses no identifier that could match a real product", not risky,
      f"plausible codes in the template: {risky}")

# The planner joins the name and the strength, so a strength inside the name
# makes the product "Paracetamol 500mg 500mg".
by_head = {h: (a, b) for h, a, b in up.EXAMPLE_COLUMNS}
names = [n for n in by_head.get("name", ()) if n]
strengths = [s for s in by_head.get("strength", ()) if s]
doubled = [n for n in names if any(s.lower() in n.lower() for s in strengths)]
check("does not repeat the strength inside the name", not doubled,
      f"names carrying their own strength: {doubled}")

print(f"\n  {passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
