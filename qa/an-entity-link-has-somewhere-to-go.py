"""Every entity kind points at a route the router actually has.

WHY THIS GUARD EXISTS

`entityRoutes.ts` is the one place that turns "a journal, id 41" into a URL,
and `EntityLink` is used in about eighty tables. When one of its entries
names a path the router does not have, React Router matches nothing and the
reader lands on the dashboard: no error, no missing-page screen, just the
wrong screen and somebody assuming they misclicked. That is the worst shape a
broken link can take, because nothing anywhere reports it.

It had been wrong for journals: the map said `/ledger/journal/:id` and
App.tsx routes `/ledger/entries/:id`, so every link to a ledger entry in the
product went to the dashboard.
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

app = (SRC / "App.tsx").read_text(encoding="utf-8")
routes = {shape(p) for p in re.findall(r'path="([^"]+)"', app)}
check(f"the router declares routes ({len(routes)})", len(routes) > 20)

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
