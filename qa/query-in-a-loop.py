"""Database calls made once per row, found in the source rather than by timing.

`n1-sweep.py` measures what an endpoint costs, which is the honest test — but it
only walks the parameterless paths the front end calls, so a detail endpoint, a
service function or anything added since is invisible to it. This reads the code
instead and looks for the shape that causes it: a query inside a loop or a
comprehension.

It found the letterhead reading twenty settings one at a time — twenty round
trips before every document this pharmacy prints, which is nothing on SQLite and
close to two seconds on the hosted database.

WHAT COUNTS

A `db.query(...)`, `db.get(...)`, `db.execute(...)` or a call to a known
per-row helper, appearing inside a `for` body, a comprehension, or a generator,
where the loop is not itself iterating over the query.

WHAT DOES NOT

Loops over a *fixed* list — the seeded chart of accounts, a handful of named
subledgers — cost a bounded number of queries however much data there is, so
they are reported separately rather than counted. A migration or a seeder is
skipped entirely: it runs once, deliberately, and not from a request.

    python qa/query-in-a-loop.py
    python qa/query-in-a-loop.py --all      # including the bounded ones
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "backend" / "app"

#: Run once, deliberately, never from a request.
SKIP = {"migrate.py", "realseed.py", "demo.py", "tenancy_backfill.py",
        "backup.py", "backup_verify.py", "parity.py"}

#: Helpers that are themselves a query are worked out, not listed.
#:
#: The first version listed names — `_row`, `balance`, `summarise` — and
#: reported fifty-two findings, most of them functions that only format a row
#: they were handed. An audit that is wrong four times in five is one nobody
#: reads, which is worse than not having it. So each file's own functions are
#: parsed first and only those whose bodies actually touch the database count.

#: Names that make a loop bounded: a fixed table of constants, not data.
BOUNDED_SOURCES = {"CHART", "COMPANY_FIELDS", "SECTIONS", "SUBLEDGERS",
                   "AGE_BANDS", "BANDS", "SEVERITIES", "WANTED_INDEXES",
                   "RELAXED_NULLABLE", "ADDED_COLUMNS", "TYPES", "VALID_TYPES"}


def direct_calls(node: ast.AST) -> list[str]:
    """Database calls made right here, on a session object."""
    out = []
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        f = sub.func
        if isinstance(f, ast.Attribute) \
                and f.attr in ("query", "get", "execute", "scalar", "scalars") \
                and isinstance(f.value, ast.Name) \
                and f.value.id in ("db", "session", "sess"):
            out.append(f"db.{f.attr}(…)")
    return out


def querying_functions(tree: ast.Module) -> set[str]:
    """Functions in this file whose own body touches the database.

    One pass, then a second to catch a helper that calls a helper. Two levels
    is enough here and stops short of building a call graph, which would be a
    lot of machinery for a check whose whole value is being cheap to run.
    """
    bodies = {n.name: n for n in ast.walk(tree)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    direct = {name for name, fn in bodies.items() if direct_calls(fn)}
    for _ in range(2):
        for name, fn in bodies.items():
            if name in direct:
                continue
            for sub in ast.walk(fn):
                if isinstance(sub, ast.Call):
                    called = (sub.func.id if isinstance(sub.func, ast.Name)
                              else getattr(sub.func, "attr", ""))
                    if called in direct:
                        direct.add(name)
                        break
    return direct


def query_calls(node: ast.AST, helpers: set[str]) -> list[str]:
    """Every database call in this subtree, named — direct or through a helper
    that this file defines and that does query."""
    out = direct_calls(node)
    for sub in ast.walk(node):
        if not isinstance(sub, ast.Call):
            continue
        f = sub.func
        name = f.id if isinstance(f, ast.Name) else getattr(f, "attr", "")
        if name in helpers:
            out.append(f"{name}(…)")
    return out


def source_name(node: ast.AST) -> str:
    """What a loop iterates over, as far as it can be named."""
    while isinstance(node, (ast.Attribute, ast.Subscript)):
        node = node.value
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Call):
        return source_name(node.func)
    return ""


def bounded(iter_node: ast.AST) -> bool:
    name = source_name(iter_node)
    if name in BOUNDED_SOURCES:
        return True
    # A literal list or tuple written inline is bounded by construction.
    return isinstance(iter_node, (ast.List, ast.Tuple, ast.Dict, ast.Set))


def main() -> int:
    show_all = "--all" in sys.argv
    findings: list[tuple[str, int, str, str, bool]] = []

    for path in sorted(APP.rglob("*.py")):
        if path.name in SKIP or "__pycache__" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        helpers = querying_functions(tree)

        for node in ast.walk(tree):
            if isinstance(node, ast.For):
                iters, body = [node.iter], node.body
            elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp,
                                   ast.GeneratorExp)):
                iters = [g.iter for g in node.generators]
                body = ([node.elt] if hasattr(node, "elt")
                        else [node.key, node.value])
            else:
                continue

            calls = []
            for part in body:
                calls += query_calls(part, helpers)
            # A loop whose *source* is the query is not the defect — that is
            # one query and a walk over its rows.
            calls = [c for c in calls if c]
            if not calls:
                continue
            is_bounded = all(bounded(i) for i in iters)
            rel = path.relative_to(ROOT).as_posix()
            findings.append((rel, node.lineno, ", ".join(sorted(set(calls))),
                             source_name(iters[0]) or "?", is_bounded))

    unbounded = [f for f in findings if not f[4]]
    fixed = [f for f in findings if f[4]]

    if unbounded:
        print("A query per row — these grow with the data\n")
        for rel, line, calls, src, _ in unbounded:
            print(f"  {rel}:{line}")
            print(f"      per {src or 'item'}: {calls}")
        print()
    print(f"{len(unbounded)} loop(s) that query once per row"
          f" · {len(fixed)} bounded by a fixed list")

    if fixed and show_all:
        print("\nBounded — a fixed number of queries however much data there is\n")
        for rel, line, calls, src, _ in fixed:
            print(f"  {rel}:{line}  per {src}: {calls}")

    return 1 if unbounded else 0


if __name__ == "__main__":
    raise SystemExit(main())
