"""Find columns that are reported but never populated.

    python qa/dormant-fields.py            # summary
    python qa/dormant-fields.py --all      # every finding, including dead columns

A dormant field is one the code reads, displays, or serialises, and nothing ever
writes. It is worse than a missing feature. A missing feature is visibly absent;
a dormant field renders a real-looking value, 0, or an empty string, in a
column with a heading, and everybody downstream treats it as an answer.

Three were found by accident in a single day:

  shifts.run_number     Allocated nowhere. Every cash-up in the system was
                        "run 0", printed on the screen the whole cash-up is
                        keyed on.
  products.sep_price    The published price ceiling. The price-file importer
                        aliased a SEP column to the selling price instead, so
                        this stayed 0 on all 545 products while the pharmacy
                        was set to charge the ceiling.
  products.mmap_price   Read by pricing.py to cap what a scheme is charged, but
                        only when above zero, so `apply_mmap` on a scheme had
                        silently never applied.

None were found by a typecheck, a test, or a build. All three were found by
someone looking at a value and asking where it came from. Hence this.

HOW IT DECIDES

Three signals, because no one of them is trustworthy alone:

  written   Does any Python in backend/app assign it? Direct attribute writes,
            constructor keywords, literal setattr, and raw UPDATE statements.
  reachable Is it a field on any Pydantic model in the app? That is what makes a
            column settable through the API, and it is how most of this app
            writes — `Patient(**body.model_dump())` names no column at all.
  populated Does any row hold something other than the column's default?

  never written + never populated   -> dormant. The finding this exists for.
  never written + populated         -> written by seed or migration only. Listed
                                       separately; usually reference data.
  written + never populated         -> reported last, and weak on purpose. It
                                       cannot distinguish "no row ever holds a
                                       value" from "every row holds exactly the
                                       default", and for a column like
                                       `remittances.status = "imported"` the
                                       default IS the normal value. All 132 rows
                                       carry it and the column is working
                                       perfectly. Treat this section as trivia
                                       unless the default is implausible.

WHAT IT STILL CANNOT SEE

Reachable through the API is not the same as offered on a screen. `bin_location`
was on ProductBase the whole time and no form had a field for it, so all 545
products carried NULL: the API would have accepted one had anything sent it.
Closing that gap needs someone to look at the form, which no static check does.

Findings are a list to look at, not a defect list. Each of the first run's 14 had
to be read individually: five were real, and the rest were columns written by a
splat or a dynamic setattr, which is why the `reachable` signal exists.
"""
import ast
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
# The SQLite URL in the app config is relative, so it resolves against the
# working directory. Run from the repository root, this script connected to a
# database file that did not exist: no tables, every check skipped, and a
# confident "dormant 0 | seed-only 0 | unexercised 0" over an empty schema.
# Nothing in the output hinted that it had examined nothing.
os.chdir(ROOT / "backend")

# Columns that are meant to be empty until something happens, and whose emptiness
# in a demo database says nothing. Listed rather than guessed at so the reasoning
# is visible and arguable.
EXPECTED_EMPTY = {
    "closed_at", "cancelled_at", "deleted_at", "voided_at", "settled_at",
    "reversed_at", "deferred_at", "abandoned_at", "response_message",
    "error_code", "notes", "reason", "deferred_reason", "rejection_reason",
}

# Findings that have been read and judged to be correct as they are. Kept here
# with the reason rather than deleted from the schema, so the next run does not
# re-raise them and nobody has to work out the answer twice. Anything not on this
# list and not fixed is still an open question.
ACCEPTED = {
    ("accounts", "parent_code"):
        "Dead column: read nowhere. The chart is flat and nothing walks a parent.",
    ("accounts", "section"):
        "An override, and its absence is designed for — statements._section() "
        "derives a conservative section from the account type and code, because "
        "existing charts predate the column.",
    ("claims", "authorisation"):
        "Superseded by the authorisations table. Storing only a number is the "
        "mistake that model was written to avoid: an authorisation has an expiry "
        "and a balance, and the draw against it is what a claim checks.",
}


def sources() -> list[tuple[str, str]]:
    """Every Python file in the app, as (path, text)."""
    out = []
    for path in sorted((ROOT / "backend" / "app").rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        out.append((str(path), path.read_text(encoding="utf-8", errors="replace")))
    return out


def written_names(files: list[tuple[str, str]]) -> set[str]:
    """Every name the app actually assigns to a column.

    Parsed rather than matched. The first version of this used regexes and was
    useless in a way that took a while to see: `\\bname\\s*=` matches any local
    variable that happens to share a column's name, and a dict-literal pattern
    matched `"run_number": getattr(shift, "run_number")`, which is a *read*.
    Between them, almost every column looked written, so the two categories that
    matter came back empty and the report read as a clean bill of health.

    It would have missed `shifts.run_number`, the field that prompted writing
    this. That is now checked for directly in main().

    Counted as a write:
      obj.col = ...            attribute assignment, including += and friends
      Model(col=...)           a keyword argument to any Capitalised call
      setattr(obj, "col", ...)
      UPDATE ... SET col =     inside a string literal
    """
    names: set[str] = set()

    for path, text in files:
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            # obj.col = value  /  obj.col += value  /  obj.col: T = value
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
                targets = [node.target]
            else:
                targets = []
            for target in targets:
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Attribute):
                        names.add(sub.attr)

            if isinstance(node, ast.Call):
                # A keyword argument to a constructor: Shift(run_number=...).
                # Restricted to Capitalised callees so that helper functions with
                # a same-named parameter do not count as storing anything.
                func_name = ""
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr
                if func_name[:1].isupper():
                    for kw in node.keywords:
                        if kw.arg:
                            names.add(kw.arg)
                if func_name == "setattr" and len(node.args) >= 2:
                    literal = node.args[1]
                    if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
                        names.add(literal.value)

            # Raw SQL. `_fill_null_text` and the migration helpers write columns
            # that appear nowhere as Python attributes.
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for match in re.finditer(r"SET\s+([a-z_]+)\s*=", node.value, re.I):
                    names.add(match.group(1))

    return names


def schema_fields() -> set[str]:
    """Names declared as fields on a request or response schema.

    A third signal, added after the first real run. The app writes most columns by
    splatting a validated payload — `Patient(**body.model_dump())`, or a loop of
    `setattr(obj, field, value)` over `model_dump(exclude_unset=True)`. Neither
    names the column anywhere a parser can see it, so four columns I had just
    made settable still came back as dormant.

    Being a field on a schema is what makes a column reachable through the API.
    It does not prove a screen offers it — that is a separate question, and the
    reason `products.bin_location` was worth fixing even though the column was
    already in ProductBase.
    """
    names: set[str] = set()
    # Every module, not just schemas.py. Several routers declare their own request
    # models inline — branches_router defines `responsible_pharmacist` on one —
    # and scanning only schemas.py reported those columns as unreachable when the
    # API accepts them perfectly well.
    for _path, text in sources():
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                # `field: type = default` — a Pydantic field declaration.
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    names.add(stmt.target.id)
    return names


def _detector_finds_known_case():
    """Run the analysis over the two files that used to leave run_number dormant.

    Returns True if the old code is correctly seen as *not* writing it, False if
    the detector claims otherwise, and None when git cannot supply the old
    revision (a shallow clone, a dirty checkout elsewhere) — in which case the
    caller simply skips the check rather than failing on it.
    """
    old = "1860dc8~1"
    wanted = ("backend/app/routers/shifts_router.py", "backend/app/services/cashup.py")
    recovered = []
    for path in wanted:
        try:
            text = subprocess.run(
                ["git", "show", f"{old}:{path}"],
                cwd=ROOT, capture_output=True, text=True, timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if text.returncode != 0 or not text.stdout:
            return None
        recovered.append((path, text.stdout))

    return "run_number" not in written_names(recovered)


def main() -> int:
    show_all = "--all" in sys.argv

    from sqlalchemy import func, inspect as sa_inspect

    from app import models  # noqa: F401  (registers the mappers)
    from app.database import SessionLocal, engine
    from app.models import Base

    files = sources()
    written = written_names(files)
    reachable = schema_fields()

    # Does the detector find the thing it was built to find? `shifts.run_number`
    # was dormant until commit 1860dc8 and is written now, so the check has to be
    # run against the code as it was before that: if the parser says the old
    # version wrote it, this whole report is noise.
    proof = _detector_finds_known_case()
    if proof is not None and proof is False:
        print("FAIL: the detector reports run_number as written in the commit "
              "where it demonstrably was not — the analysis is wrong")
        return 2

    # And the opposite direction: columns that are obviously written must be seen.
    for known in ("unit_price", "total", "quantity_on_hand", "run_number"):
        if known not in written:
            print(f"FAIL: the detector cannot see writes to {known!r} in the "
                  f"current code — the analysis is wrong, not the schema")
            return 2

    db = SessionLocal()
    live_tables = set(sa_inspect(engine).get_table_names())

    # Refuse to report on a database that is not there. Without this the script
    # skipped all 77 tables and printed a clean bill of health.
    if len(live_tables) < 20:
        print(f"FAIL: only {len(live_tables)} tables visible at "
              f"{engine.url} — pointing at the wrong database, so 'no findings' "
              f"would mean nothing")
        return 2

    dormant, seeded, unexercised = [], [], []

    for table in Base.metadata.sorted_tables:
        if table.name not in live_tables:
            continue
        try:
            rows = db.query(func.count()).select_from(table).scalar() or 0
        except Exception:
            continue
        if not rows:
            continue

        for column in table.columns:
            if column.primary_key or column.foreign_keys:
                continue
            name = column.name
            if name in EXPECTED_EMPTY:
                continue
            if (table.name, name) in ACCEPTED:
                continue

            default = getattr(column.default, "arg", None)
            if callable(default):
                continue  # a callable default is populated by definition

            # "Populated" means: any row holding something other than the
            # default and not NULL. For text the default is usually ''.
            col = table.c[name]
            try:
                condition = col.isnot(None)
                if isinstance(default, (int, float)) and not isinstance(default, bool):
                    condition = condition & (col != default)
                elif isinstance(default, str):
                    condition = condition & (col != default)
                elif default is None:
                    pass
                else:
                    continue  # booleans: false-by-default tells us nothing
                filled = db.query(func.count()).select_from(table).filter(condition).scalar() or 0
            except Exception:
                continue

            # Either a parser-visible write, or a field on a schema the API
            # validates and splats into the model. The second is how most of this
            # app writes, so leaving it out produced four false findings.
            is_written = name in written or name in reachable
            if not is_written and not filled:
                dormant.append((table.name, name, rows))
            elif not is_written and filled:
                seeded.append((table.name, name, filled, rows))
            elif is_written and not filled:
                unexercised.append((table.name, name, rows))

    db.close()

    print(f"\n{'=' * 72}\nDORMANT — nothing writes them, and no row holds a value\n{'=' * 72}")
    if dormant:
        for t, c, rows in dormant:
            print(f"  {t}.{c:<28} ({rows} rows in the table)")
    else:
        print("  none")

    print(f"\n{'-' * 72}\nWRITTEN BY SEED OR MIGRATION ONLY — populated, but no code writes them\n{'-' * 72}")
    for t, c, filled, rows in (seeded if show_all else seeded[:15]):
        print(f"  {t}.{c:<28} {filled}/{rows} rows carry a value")
    if not show_all and len(seeded) > 15:
        print(f"  … and {len(seeded) - 15} more (--all)")

    print(f"\n{'-' * 72}\nWRITER EXISTS BUT NOTHING IS STORED — may never fire, may just be unused\n{'-' * 72}")
    for t, c, rows in (unexercised if show_all else unexercised[:20]):
        print(f"  {t}.{c:<28} ({rows} rows)")
    if not show_all and len(unexercised) > 20:
        print(f"  … and {len(unexercised) - 20} more (--all)")

    print(f"\ndormant {len(dormant)} | seed-only {len(seeded)} | unexercised {len(unexercised)}")
    return 1 if dormant else 0


if __name__ == "__main__":
    raise SystemExit(main())
