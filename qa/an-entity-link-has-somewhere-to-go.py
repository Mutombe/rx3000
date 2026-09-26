"""Every entity kind points at a route the router actually has.

WHY THIS GUARD EXISTS

`entityRoutes.ts` is the one place that turns "a journal, id 41" into a URL,
and `EntityLink` is used in about eighty tables. When one of its entries
names a path the router does not have, React Router matches nothing and the
reader lands on the dashboard: no error, no missing-page screen, just the
wrong screen and somebody assuming they misclicked. That is the worst shape a
broken link can take, because nothing anywhere reports it.

It had been wrong for journals: the map said `/ledger/journal/:id` and the
router declares `/ledger/entries/:id`, so every link to a ledger entry in the
product went to the dashboard.

AND THEN THIS GUARD ITSELF WENT WRONG, WHICH IS WORTH MORE THAN THE BUG.

It read `App.tsx`, because that is where every route lived when it was
written. The portal work then moved the authenticated routes into `Staff.tsx`
— deliberately, so a patient opening a link on a phone does not download the
whole dispensary — and left six portal routes behind in App.tsx.

So the guard found six routes, failed to resolve all twenty-eight kinds, and
reported every link in the product as broken. Every one of them works. A guard
that reports twenty-eight faults where there are none gets read once, disbelieved,
and never read again, which costs more than the thing it was watching for.

It reads wherever the routes are now, and it FAILS if it finds too few of them
rather than quietly reporting the consequence — a route file that has moved
again should say so in its own words rather than as a wall of broken links.
"""
import pathlib
import re
import sys

SRC = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "src"

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


def shape(path: str) -> str:
    """A path with its parameter names flattened, so :id and :ref compare."""
    return re.sub(r":[A-Za-z_]+", ":x", path.rstrip("/"))


print("\n  every entity kind has somewhere to go\n")

# Every file that declares routes, not one named file. The split between the
# portal shell and the staff shell is the point of that design, and a guard
# that knows about only one half of it is a guard reporting on half a product.
declaring = sorted(p for p in SRC.glob("*.tsx")
                   if 'path="' in p.read_text(encoding="utf-8"))
routes = set()
for path in declaring:
    routes |= {shape(m) for m in
               re.findall(r'path="([^"]+)"', path.read_text(encoding="utf-8"))}
check(f"the router declares routes ({len(routes)} across "
      f"{', '.join(p.name for p in declaring)})", len(routes) > 20,
      "too few to be the whole router. The routes have moved again: find the "
      "file that declares them and make sure it is under frontend/src/*.tsx, "
      "because everything below this line is measured against them.")

kinds = re.findall(r"(\w+): \(id: Id\) => `([^`]+)`",
                   (SRC / "entityRoutes.ts").read_text(encoding="utf-8"))
check(f"entityRoutes declares kinds ({len(kinds)})", len(kinds) > 10)

missing = [(name, path) for name, path in kinds
           if shape(path.replace("${id}", ":x")) not in routes]
check("every kind resolves to a declared route", not missing,
      "; ".join(f"{n} -> {p}" for n, p in missing)
      + "  (React Router matches nothing and the reader lands on the dashboard)")

print(f"\n  {passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
