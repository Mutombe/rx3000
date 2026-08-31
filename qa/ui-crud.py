"""What can somebody actually do on each list screen?

A previous version of this question was answered from the API, which was the
wrong answer to the right question. An endpoint that exists and no screen calls
is not a capability a pharmacy has — it is a capability the *codebase* has, and
the difference is the whole gap between software that works and software that
demos.

So this reads the screens. For every page that shows a list, it reports which
of these a person sitting in front of it can do:

    add      a create control on the page
    find     a search box
    filter   a control that narrows the list
    open     rows lead somewhere
    edit     a way to change a row without leaving
    select   tick boxes, or any multi-row selection
    bulk     an action that applies to the selection
    remove   a delete or retire control

`select` and `bulk` are reported separately because they fail separately: a
table with tick boxes and no action is a table with decoration, and an action
with nothing to apply it to cannot be reached. Both together are the thing that
is almost always missing, and it is the one that hurts at four thousand rows —
a pharmacy re-pricing four hundred lines one at a time does not re-price them.

WHAT IT CANNOT SEE

It reads source, so it finds controls that exist, not controls that work. A
search box wired to nothing counts as `find` here. That is a real limit and the
reason this reports rather than passes: it narrows where to look, it does not
certify.

    python qa/ui-crud.py
    python qa/ui-crud.py --gaps
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGES = ROOT / "frontend" / "src" / "pages"

#: The screens a pharmacy manages records on. Named rather than discovered, so
#: the report covers the ones that matter instead of every file with a table.
SCREENS = [
    "Patients", "Stock", "StockCategories", "Suppliers", "Prescribers",
    "Prescriptions", "Orders", "Staff", "Branches", "Claiming", "Drivers",
    "Deliveries", "ToFollows", "Laybys", "Shifts", "Repeats", "Leads",
    "Helpdesk", "Marketing", "Payables", "Reminders", "DispensingHistory",
    "Recall", "Samples", "StockTake",
]

SIGNALS = {
    # (label, what its presence looks like in the source)
    "add": (r'New\s|Add\s|<Plus|"\+ ?"|onClick=\{\(\) => set(Adding|Creating|New)'),
    "find": (r'type="search"|placeholder="Search|page-search|\bsetQuery\b|\bsetSearch\b|[?&]q=\$'),
    "filter": (r'<Select\b|setStatus\(|setTab\(|PageTabs|setFilter|<Filters\b|setBranch'),
    "open": (r'<RowLink|<EntityLink|useNavigate\(\)|<Link\s'),
    "edit": (r'setEditing|onEdit|<PencilSimple|api\.put\(|api\.patch\(|useOptimisticList'),
    # `SelectRow`/`SelectAll`/`useSelection` are this codebase's own primitives
    # for the job. Added after the first run reported a screen as having no
    # selection when it had exactly that — an audit that does not know the
    # shape of the thing it audits reports absence where there is none, and one
    # false absence is enough for people to stop reading the whole report.
    "select": (r'type="checkbox"|selectedIds|setSelected|<Checkbox\b|selection|'
               r'<SelectRow|<SelectAll|useSelection'),
    "bulk": (r'selected\.(map|forEach|length)|bulk|<BulkBar|'
             r'Promise\.all\(\s*selected|applyToSelected|'
             r'for \(const id of selected|picked\.rows'),
    "remove": (r'api\.delete\(|onDelete|<Trash|Retire|Deactivate|setRemoving'),
}


def scan(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    return {k: bool(re.search(p, text)) for k, p in SIGNALS.items()}


def main() -> int:
    only_gaps = "--gaps" in sys.argv
    cols = list(SIGNALS)

    print(f"  {'':<20} " + "".join(f"{c:<8}" for c in cols))
    print(f"  {'-' * (20 + 8 * len(cols))}")

    missing_bulk: list[str] = []
    missing_find: list[str] = []
    seen = 0

    for name in SCREENS:
        path = PAGES / f"{name}.tsx"
        if not path.exists():
            print(f"  {name:<20} no such page")
            continue
        seen += 1
        got = scan(path)
        row = f"  {name:<20} " + "".join(
            f"{('Y' if got[c] else '·'):<8}" for c in cols)
        gap = not (got["select"] and got["bulk"])
        if gap:
            missing_bulk.append(name)
        if not got["find"]:
            missing_find.append(name)
        if not only_gaps or gap or not got["find"]:
            print(row)

    print()
    print(f"  {seen} list screens read")
    print(f"  {seen - len(missing_bulk)} let you act on many rows at once")
    if missing_bulk:
        print(f"\n  no multi-row selection and action:")
        for n in missing_bulk:
            print(f"    {n}")
    if missing_find:
        print(f"\n  no search box — unusable once the table is long:")
        for n in missing_find:
            print(f"    {n}")
    # Reported, never failed. Not every screen should have every control: a
    # shift must not be editable and a dispensing must not be deletable, and a
    # check that demanded eight ticks everywhere would be demanding the wrong
    # thing. This is a map, so the holes are visible instead of remembered.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
