"""Every Python file in the backend parses, and every service imports.

WHY THIS GUARD EXISTS

`services/settlements.py` carried a broken indent for several commits:

    for advice in advices:
        # Both the grouping key and the name shown beside the row, so it
    # has to read as a sentence rather than as a symbol.
    key = (advice.funder_id or "not named").upper()
        row = funders.setdefault(key, {

A comment and the line under it had been pulled back four spaces, almost
certainly by a bulk edit across many files. The file could not be parsed at
all, so BOTH settlement endpoints answered 500 and the whole Settlements
screen — by funder, and claims a funder is holding — was dead in production
for as long as it took anybody to look.

WHY NOTHING CAUGHT IT.

The server started perfectly. Every other screen worked. `settlements` is
imported INSIDE the two functions that need it rather than at module scope,
which is a deliberate and reasonable pattern here — it keeps a cold start
quick — and its cost is that a file with a syntax error in it is not read
until somebody opens that one screen. The tests that run in this repo did not
touch it. The frontend typechecks, which says nothing about Python.

So the failure was invisible from every direction except opening the page, and
the page is one a pharmacy opens monthly.

WHAT IS CHECKED

Every file parses, which is cheap and catches the fault above. Then every
module under `services/` and `routers/` is actually IMPORTED, because parsing
only proves the syntax: a bad name at module scope, a circular import or a
missing dependency all pass a parse and fail at the moment somebody needs the
screen.

Deliberately not every module in the tree: importing `migrate` or `main` for a
syntax check would start the world. Those are covered by the server booting,
which happens on every deploy.
"""
import ast
import importlib
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
APP = BACKEND / "app"

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


print("\n  every module parses\n")

files = sorted(APP.rglob("*.py"))
broken = []
for path in files:
    try:
        ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        broken.append(f"{path.relative_to(ROOT).as_posix()}:{exc.lineno} {exc.msg}")

check(f"every backend file parses ({len(files)} files)", not broken,
      "; ".join(broken)
      + ". A module imported inside a function fails only when somebody opens "
        "the screen that needs it, which can be months.")

# ---------------------------------------------------------------------------
# And imports, which parsing does not prove
# ---------------------------------------------------------------------------
sys.path.insert(0, str(BACKEND))

modules = [f"app.{p.relative_to(APP).with_suffix('').as_posix().replace('/', '.')}"
           for p in sorted((APP / "services").rglob("*.py"))
           + sorted((APP / "routers").rglob("*.py"))
           if p.name != "__init__.py"]

unimportable = []
for name in modules:
    try:
        importlib.import_module(name)
    except Exception as exc:                            # noqa: BLE001
        unimportable.append(f"{name}: {type(exc).__name__}: {exc}")

check(f"every service and router imports ({len(modules)} modules)",
      not unimportable, "; ".join(unimportable[:3]))

print(f"\n  {passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
