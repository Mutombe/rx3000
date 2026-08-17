"""Find fields the API accepts that no screen offers.

    python qa/form-coverage.py

The gap left over from qa/dormant-fields.py. That script asks whether a column is
reachable through the API; this asks whether anybody can actually reach it.
`products.bin_location` was on ProductBase for weeks, would have been accepted by
the API the whole time, and was NULL on all 545 products because no form had a
field for it. A static check on the backend cannot see that, because nothing on
the backend is wrong.

HOW IT DECIDES

For every field on a request schema — the models a POST or PUT body validates
against — does the string appear anywhere in frontend/src? If it does not, no
screen can be sending it, so the field is unreachable in practice.

  request schema   a Pydantic model in the app that is used as a body parameter,
                   found by reading the function signatures rather than guessing
                   from class names.

WHAT A FINDING MEANS, AND WHAT IT DOES NOT

A hit means "no file in the front end mentions this name". That is strong evidence
nothing sends it, and weak evidence about whether it should. Plenty of fields are
legitimately server-set, internal, or driven by a different client — the desktop
app and the patient portal are separate surfaces.

It cannot see a field that is mentioned but not usefully offered: a name that
appears only in a type definition, or in a form nobody can reach. Mentioned is the
floor, not the bar.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "backend" / "app"
FRONTEND = ROOT / "frontend" / "src"

# Names the server owns. Nothing on a screen should be sending these, so their
# absence from the front end is correct rather than a gap.
SERVER_OWNED = {
    "id", "created_at", "updated_at", "csv_text", "apply", "password",
    "approver", "context", "action", "token", "value", "key", "reason",
    "notes", "limit", "offset", "page", "per_page", "q", "query",
}


def request_schema_names() -> dict[str, set[str]]:
    """Map each request-body schema to the field names it declares.

    Which classes are request bodies is read from the route handlers: a parameter
    annotated with a Pydantic model, on a function decorated with post or put.
    Naming conventions were the obvious shortcut and the wrong one — this app has
    request models called CountIn, DispenseRequest, MedicalAidTerms and
    PriceImportRequest, and no single suffix covers them.
    """
    bodies: set[str] = set()
    classes: dict[str, set[str]] = {}

    for path in sorted(APP.rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                fields = {
                    stmt.target.id
                    for stmt in node.body
                    if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
                }
                if fields:
                    classes.setdefault(node.name, set()).update(fields)

            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                writes = False
                for dec in node.decorator_list:
                    target = dec.func if isinstance(dec, ast.Call) else dec
                    name = getattr(target, "attr", "") or getattr(target, "id", "")
                    if name in ("post", "put", "patch"):
                        writes = True
                if not writes:
                    continue
                for arg in list(node.args.args) + list(node.args.kwonlyargs):
                    ann = arg.annotation
                    if ann is None:
                        continue
                    # schemas.Thing  or  Thing
                    if isinstance(ann, ast.Attribute):
                        bodies.add(ann.attr)
                    elif isinstance(ann, ast.Name):
                        bodies.add(ann.id)

    return {name: classes[name] for name in sorted(bodies) if name in classes}


def frontend_text() -> str:
    parts = []
    for path in sorted(FRONTEND.rglob("*")):
        if path.suffix in (".ts", ".tsx", ".js", ".jsx") and path.is_file():
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parts)


def main() -> int:
    schemas = request_schema_names()
    if len(schemas) < 10:
        print(f"FAIL: only {len(schemas)} request schemas found — the signature "
              f"scan is broken, so 'no gaps' would mean nothing")
        return 2

    ui = frontend_text()
    if len(ui) < 100_000:
        print(f"FAIL: only {len(ui)} characters of front end read — wrong path?")
        return 2

    print(f"{len(schemas)} request schemas, {len(ui):,} characters of front end\n")

    findings: list[tuple[str, list[str]]] = []
    for schema, fields in schemas.items():
        missing = sorted(
            f for f in fields
            if f not in SERVER_OWNED and f not in ui
        )
        if missing:
            findings.append((schema, missing))

    total = sum(len(m) for _, m in findings)
    if not findings:
        print("Every request field is mentioned somewhere in the front end.")
        return 0

    print(f"{'=' * 72}\nACCEPTED BY THE API, NOT MENTIONED IN ANY SCREEN\n{'=' * 72}")
    for schema, missing in sorted(findings, key=lambda p: -len(p[1])):
        print(f"\n  {schema}")
        for field in missing:
            print(f"      {field}")

    print(f"\n{total} fields across {len(findings)} schemas")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
