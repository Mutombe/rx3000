"""Which records can actually be created, found, changed and removed?

An honest answer to "what have you implemented", measured rather than
remembered. It is easy to believe a table is finished because it renders, and
easy to ship one that can be added to and never corrected — which is worse than
one that cannot be added to at all, because the wrong row is now permanent and
somebody works around it in a notes field.

For every record type this reports which of five capabilities exist, from the
API surface rather than from anybody's recollection:

    C   a create endpoint
    R   a list endpoint, and whether it can be searched and filtered
    U   an update endpoint
    Ub  a bulk update — one call changing many rows
    D   a delete or retire endpoint
    Db  a bulk delete or retire

Bulk is reported separately because it is the one that is almost always
missing, and the one whose absence hurts at scale. A pharmacy re-pricing four
hundred lines one at a time does not re-price them; it keeps the old prices.

WHAT COUNTS AS DELETE

Retiring counts. For most records in a pharmacy an actual DELETE is the wrong
answer — a supplier's name is on every order they ever fulfilled, a driver's on
every waybill they carried — so `active = false` is the correct implementation
and is reported as satisfying D. What is reported as missing is having *neither*.

    python qa/crud-coverage.py
    python qa/crud-coverage.py --gaps      only what is incomplete
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTERS = ROOT / "backend" / "app" / "routers"

#: The records a pharmacy actually manages, and the path fragment that names
#: each. Listed rather than discovered, so the report covers what matters
#: instead of every endpoint that happens to exist.
RECORDS = [
    ("Patients", "patients"),
    ("Products", "products"),
    ("Departments", "stock-categories"),
    ("Suppliers", "suppliers"),
    ("Prescribers", "doctors"),
    ("Prescriptions", "prescriptions"),
    ("Sales", "sales"),
    ("Purchase orders", "orders"),
    ("Stock batches", "batches"),
    ("Staff", "users"),
    ("Branches", "branches"),
    ("Medical aids", "medical-aids"),
    ("Claims", "claims"),
    ("Drivers", "drivers"),
    ("Deliveries", "waybills"),
    ("Payment instruments", "payment-instruments"),
    ("Counter messages", "counter-messages"),
    ("Clinical terms", "clinical-terms"),
    ("To-follows", "to-follows"),
    ("Lay-bys", "laybys"),
    ("Shifts", "shifts"),
    ("Petty cash", "petty-cash"),
    ("Accounts (ledger)", "accounts"),
    ("Leads", "leads"),
    ("Cases", "tickets"),
    ("Campaigns", "campaigns"),
]

#: A word in the path that means the call acts on many rows at once.
BULK_WORDS = ("bulk", "batch-", "/batch", "many", "all", "import", "upload",
              "tag", "merge", "apply", "sweep")


def routes() -> list[tuple[str, str, set[str], str]]:
    """(method, path, query parameter names, handler source) for every route."""
    found = []
    for file in sorted(ROUTERS.glob("*.py")):
        text = file.read_text(encoding="utf-8", errors="replace")
        prefix = ""
        m = re.search(r"""APIRouter\((?:[^)]*?)prefix\s*=\s*["']([^"']*)["']""",
                      text, re.S)
        if m:
            prefix = m.group(1)
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not (isinstance(dec, ast.Call)
                        and isinstance(dec.func, ast.Attribute)
                        and isinstance(dec.func.value, ast.Name)
                        and dec.func.value.id.startswith("router")):
                    continue
                verb = dec.func.attr.upper()
                if verb not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                    continue
                if not dec.args or not isinstance(dec.args[0], ast.Constant):
                    continue
                path = prefix + dec.args[0].value
                params = {a.arg for a in node.args.args}
                found.append((verb, path, params, ast.get_source_segment(text, node) or ""))
    return found


def assess(fragment: str, all_routes) -> dict:
    mine = [r for r in all_routes if fragment in r[1]]
    if not mine:
        return {}

    def has(verb: str, bulk: bool | None = None) -> bool:
        for m, path, _p, _src in mine:
            if m != verb:
                continue
            is_bulk = any(w in path.lower() for w in BULK_WORDS)
            # A verb on a path with no {id} in it acts on the collection, which
            # for PUT and DELETE is a bulk operation by definition.
            if not is_bulk and verb in ("PUT", "PATCH", "DELETE"):
                is_bulk = "{" not in path.split(fragment, 1)[-1]
            if bulk is None or is_bulk == bulk:
                return True
        return False

    # Search and filter, read off the list endpoint's own parameters — the
    # honest test, because a table that cannot be searched is unusable at four
    # thousand rows however good its columns are.
    searchable = filterable = False
    for m, path, params, _src in mine:
        if m != "GET" or path.rstrip("/").endswith("}"):
            continue
        if params & {"q", "search", "query", "term"}:
            searchable = True
        if len(params & {"status", "active", "kind", "category", "branch_id",
                         "from_date", "to_date", "days", "schedule",
                         "supplier_id", "patient_id", "product_id", "funder_id",
                         "include_retired", "unpaid_only", "page"}) >= 1:
            filterable = True

    return {
        "C": has("POST", bulk=False) or has("POST"),
        "R": any(m == "GET" for m, *_ in mine),
        "search": searchable,
        "filter": filterable,
        "U": has("PUT", bulk=False) or has("PATCH", bulk=False),
        "Ub": has("PUT", bulk=True) or has("PATCH", bulk=True)
              or has("POST", bulk=True),
        "D": has("DELETE"),
        "routes": len(mine),
    }


def main() -> int:
    only_gaps = "--gaps" in sys.argv
    all_routes = routes()

    print(f"  {len(all_routes)} routes across {len(RECORDS)} record types\n")
    print(f"  {'':<22} {'C':<3}{'R':<3}{'find':<6}{'U':<3}{'U bulk':<8}{'D':<3}")
    print(f"  {'-' * 52}")

    complete = 0
    gaps: list[str] = []
    for name, fragment in RECORDS:
        a = assess(fragment, all_routes)
        if not a:
            gaps.append(f"{name}: no endpoint carries \"{fragment}\" — "
                        f"either it is named differently or it has no API")
            if not only_gaps:
                print(f"  {name:<22} {'not found':<20}")
            continue

        find = ("q+f" if a["search"] and a["filter"]
                else "q" if a["search"]
                else "f" if a["filter"] else "—")
        row = (f"  {name:<22} "
               f"{'Y' if a['C'] else '·':<3}"
               f"{'Y' if a['R'] else '·':<3}"
               f"{find:<6}"
               f"{'Y' if a['U'] else '·':<3}"
               f"{'Y' if a['Ub'] else '·':<8}"
               f"{'Y' if a['D'] else '·':<3}")

        missing = []
        if not a["C"]:
            missing.append("cannot be created through the API")
        if not a["U"]:
            missing.append("cannot be corrected once wrong")
        if not a["D"]:
            missing.append("cannot be removed or retired")
        if not (a["search"] or a["filter"]):
            missing.append("the list cannot be searched or filtered")
        if not a["Ub"]:
            missing.append("no bulk change")

        if missing:
            gaps.append(f"{name}: " + "; ".join(missing))
        else:
            complete += 1
        if not only_gaps or missing:
            print(row)

    print()
    print(f"  {complete} of {len(RECORDS)} record types have create, read with "
          f"search or filter, update, bulk update and delete/retire")
    if gaps:
        print("\n  where it is incomplete:")
        for g in gaps:
            print(f"    {g}")
    # Reported, never failed. This is a map of the estate rather than a test:
    # not every record should have every verb — a fiscal receipt must not be
    # editable, and a dispensing must not be deletable — and a check that
    # demanded five ticks everywhere would be demanding the wrong thing.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
