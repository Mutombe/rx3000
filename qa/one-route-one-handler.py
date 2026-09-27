"""No two handlers claim the same method and path.

WHY THIS GUARD EXISTS

`to_follows_router.py` declared `@router.post("")` twice. The two bodies were
near identical — the second was the first minus `sale_id` — so nothing looked
wrong and nothing behaved wrongly enough to notice.

What it actually produced was a server and a contract that disagreed. FastAPI
matches routes in the order they are registered, so every request was served by
the FIRST handler. The OpenAPI schema is a dict keyed by path and method, so it
kept the LAST one. The published contract therefore described a body without
`sale_id` while the running code accepted one, and `sale_id` is the field that
ties a short supply to the sale it came from.

The worse half is the dead handler. It carried the better docstring, it read as
live, and anybody editing it would have watched their change do nothing at all.
Dead code that looks live is more expensive than dead code that looks dead.

WHAT IS CHECKED

Every `@router.<method>("<path>")` decorator in every router, read as source.
Source rather than the app's own route table, because a duplicate is worth
catching in the file somebody is editing, and because a router that fails to
import at all should be a different error than this one.

A path is compared after stripping the parameter NAMES: `/{owed_id}` and
`/{id}` are the same route to a router, and two handlers claiming them are the
same fault wearing different spellings.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
ROUTERS = ROOT / "backend" / "app" / "routers"

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


DECORATOR = re.compile(
    r'@router\.(get|post|put|patch|delete)\(\s*["\']([^"\']*)["\']', re.I)
#: A parameter's name is the caller's business, not the router's.
PARAM = re.compile(r"\{[^}]*\}")

print("\n  one route, one handler\n")

seen: dict[tuple[str, str, str], list[str]] = {}
files = sorted(ROUTERS.glob("*.py"))
for path in files:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    for n, line in enumerate(lines, start=1):
        m = DECORATOR.match(line.strip())
        if not m:
            continue
        method, route = m.group(1).upper(), PARAM.sub("{}", m.group(2))
        # The handler's own name, for a message somebody can act on.
        who = ""
        for ahead in lines[n:n + 6]:
            named = re.match(r"(?:async )?def (\w+)", ahead.strip())
            if named:
                who = named.group(1)
                break
        seen.setdefault((path.name, method, route), []).append(f"{who} (line {n})")

check(f"there are routes to check ({len(seen)} across {len(files)} routers)",
      len(seen) > 200)

clashes = {k: v for k, v in seen.items() if len(v) > 1}
check("no two handlers claim the same method and path", not clashes,
      "; ".join(f"{name} {method} {route or '\"\"'}: " + " and ".join(who)
                for (name, method, route), who in clashes.items())
      + ". The first registered serves every request and the last is "
        "published in the schema, so the contract and the server disagree "
        "and one of the two handlers is dead code that reads as live.")

print(f"\n  {passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
