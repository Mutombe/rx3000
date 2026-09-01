"""Every raw SQL statement, and whether it can cross a pharmacy.

The tenancy filter is applied by the ORM, which means it cannot see inside a
`text()` string — SQLAlchemy has no idea that a hand-written SELECT touches
`patients`. So raw SQL is the one place in this system where the scoping is not
automatic, and the only honest way to know it is safe is to look at all of it.

This finds every raw statement, works out which tables it touches, and reports
the ones touching tenant-scoped tables without naming `pharmacy_id`. It does not
try to be clever about whether a particular caller happens to be guarded — it
reports the surface, and a human decides.

Trusted callers are listed by file rather than guessed. A migration and a
backup genuinely do cross tenants: that is their job, and they run at startup or
behind the platform guard rather than from a request. Anything not on that list
is reachable from a request and has to justify itself.

    python qa/raw-sql-audit.py
"""
import ast
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]/"backend"/"app"

#: Files whose whole job is to cross tenants, and which no request reaches.
#: Named rather than inferred, so adding one is a decision somebody makes.
TRUSTED = {
    "migrate.py":            "schema migrations, run at startup before serving",
    "tenancy_backfill.py":   "stamps existing rows with their pharmacy, at startup",
    "database.py":           "connection setup; touches no tenant table",
    "realseed.py":           "seeding, run deliberately and never from a request",
    "backup.py":             "whole-database backup, behind the platform guard",
    "backup_verify.py":      "checks a backup file, behind the platform guard",
}


def scoped_tables() -> set[str]:
    """Ask the models which tables carry a pharmacy."""
    sys.path.insert(0, str(ROOT.parent))
    from app.database import Base                     # noqa: E402
    from app.tenancy import TenantMixin               # noqa: E402
    import app.models                                 # noqa: F401,E402

    return {m.class_.__tablename__ for m in Base.registry.mappers
            if issubclass(m.class_, TenantMixin)}


def statements(path: pathlib.Path):
    """Every string handed to text() or execute(), with its line."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
        if name not in ("text", "execute"):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                yield node.lineno, arg.value
            elif isinstance(arg, ast.JoinedStr):
                # An f-string: report it with what is literal, since the
                # interpolated part is usually a table name from a loop.
                literal = "".join(v.value for v in arg.values
                                  if isinstance(v, ast.Constant))
                yield node.lineno, literal + "  «interpolated»"


def _selects_nothing(sql: str) -> bool:
    """A probe that asks whether a table exists rather than what is in it.

    `SELECT 1 FROM batch_allocations LIMIT 1` names a tenant table and returns
    no tenant data: the constant is all it ever selects. Reporting it as a leak
    is how a check like this gets a reputation for crying wolf, and a check
    nobody believes protects nothing.
    """
    return bool(re.match(r"\s*SELECT\s+1\s+FROM\s+\w+\s+LIMIT\s+1\s*$", sql, re.I))


def tables_in(sql: str) -> set[str]:
    return {t.lower() for t in
            re.findall(r"\b(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+([A-Za-z_][A-Za-z0-9_]*)",
                       sql, re.I)}


scoped = scoped_tables()
findings, trusted_hits, clean = [], 0, 0

for path in sorted(ROOT.rglob("*.py")):
    if "__pycache__" in str(path):
        continue
    try:
        found = list(statements(path))
    except SyntaxError:
        continue
    for line, sql in found:
        touched = tables_in(sql) & scoped
        if not touched or _selects_nothing(sql):
            clean += 1
            continue
        if path.name in TRUSTED:
            trusted_hits += 1
            continue
        findings.append((path.relative_to(ROOT.parent), line, sorted(touched),
                         "pharmacy_id" in sql.lower(),
                         " ".join(sql.split())[:70]))

print(f"{len(scoped)} tenant-scoped tables")
print(f"{clean} raw statements touch none of them")
print(f"{trusted_hits} are in files whose job is to cross tenants:")
for name, why in sorted(TRUSTED.items()):
    print(f"    {name:<22} {why}")

print()
if not findings:
    print("  ok   no raw SQL outside those files touches a tenant-scoped table")
    sys.exit(0)

print(f"{len(findings)} raw statement(s) reachable from a request touch tenant data:\n")
for where, line, tables, filtered, snippet in findings:
    mark = "ok  " if filtered else "FAIL"
    print(f"  {mark} {where}:{line}")
    print(f"       tables: {', '.join(tables)}")
    print(f"       filters on pharmacy_id: {filtered}")
    print(f"       {snippet}")
sys.exit(1 if any(not f[3] for f in findings) else 0)
