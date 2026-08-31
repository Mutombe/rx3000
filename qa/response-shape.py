"""Does the screen expect the shape the endpoint actually returns?

A product detail page crashed in production with `m.map is not a function`.
The cause was not a bug in either half. `/api/stock-categories` used to return
a list of departments; it grew a count of untagged lines and became
`{"items": [...], "untagged": 41}`. The departments screen was updated. The
product page, which fetches the same endpoint to fill one dropdown, was not.

TypeScript could not catch it, and this is the important part: `api.get<T>` is
an **assertion**, not a check. Writing `api.get<Category[]>(...)` tells the
compiler the response is an array. It does not ask the server. So the code
type-checks, builds, ships, and throws on the customer's screen the moment a
component tries to iterate an object.

Nothing else covers this. The endpoint-coverage check knows the route is
called; it does not know what comes back. The build is green by construction.
Only a person opening that exact page finds it, and only if they open it.

So: read every `api.get<...[]>("/path")` in the front end, find the handler
that serves that path, and work out whether it returns a list or a dict. A
handler whose returns are all dict literals against a caller expecting an array
is the defect, stated as such.

WHAT IT DELIBERATELY DOES NOT DO

It does not run the server or call the endpoints. A check that needs a database
in a particular state gets skipped, and a skipped check is not a check. Static
reading of the `return` statements is enough to catch the whole class: a
handler that returns `{...}` on every path cannot satisfy a caller doing `.map`.

Where a handler's returns are mixed or indirect — a bare `return helper(x)` —
it says so and moves on rather than guessing. Guessing produces a list of
maybes that people learn to ignore, and an audit that cries wolf gets worked
around instead of fixed.

    python qa/response-shape.py
    python qa/response-shape.py --all      every call, including the agreeing ones
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend" / "src"
ROUTERS = ROOT / "backend" / "app" / "routers"

#: `api.get<Something[]>("/api/thing")` and the template-literal form.
#: The type argument has to end in `[]` — that is the assertion we are testing.
CALL = re.compile(
    r"""api\.get<\s*(?P<type>[^>]*?\[\])\s*>\(\s*[`"'](?P<path>/api/[^`"'?${]*)""",
    re.S,
)

#: `@router.get("/x")` — the decorator, and the def that follows it.
ROUTE = re.compile(r"""@router\.get\(\s*["'](?P<path>[^"']*)["']""")


def frontend_calls() -> list[tuple[Path, int, str, str]]:
    """Every place a screen asserts an endpoint returns an array."""
    found = []
    for file in sorted(FRONTEND.rglob("*.ts*")):
        text = file.read_text(encoding="utf-8", errors="replace")
        for match in CALL.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            found.append((file, line, match.group("path").rstrip("/"),
                          match.group("type").strip()))
    return found


def _declared_shape(decorator: ast.Call) -> str | None:
    """`response_model=list[X]` settles it without reading the body.

    FastAPI coerces the return value to this, so it is the shape that actually
    reaches the browser even where the handler builds something else.
    """
    for keyword in decorator.keywords:
        if keyword.arg != "response_model":
            continue
        value = keyword.value
        if isinstance(value, ast.Subscript):
            base = value.value
            name = (base.id if isinstance(base, ast.Name)
                    else base.attr if isinstance(base, ast.Attribute) else "")
            if name in ("list", "List"):
                return "list"
            return "dict"
        if isinstance(value, ast.Constant) and value.value is None:
            return None
        return "dict"
    return None


def _shape_of(node: ast.FunctionDef, local: dict | None = None,
              depth: int = 0) -> tuple[str, str]:
    """What this handler returns: 'list', 'dict', 'mixed', or 'unknown'.

    Read off the `return` statements themselves. A handler that returns a dict
    literal on every path cannot satisfy a caller doing `.map`, and that is the
    entire question being asked.
    """
    kinds: set[str] = set()
    detail = ""
    for child in ast.walk(node):
        if not isinstance(child, ast.Return) or child.value is None:
            continue
        value = child.value
        if isinstance(value, (ast.List, ast.ListComp)):
            kinds.add("list")
        elif isinstance(value, ast.Dict):
            kinds.add("dict")
            keys = [k.value for k in value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)]
            if keys and not detail:
                detail = "{" + ", ".join(keys[:6]) + "}"
        elif isinstance(value, ast.Call):
            # `return _rows(...)` — follow it where the helper is in this same
            # file, once. Most handlers that looked unreadable were one hop
            # from a list comprehension, and "could not read 85 of them" is not
            # a useful thing for a check to say when the answer was one lookup
            # away. Cross-file calls into a service stay unknown: guessing at
            # those produces maybes, and an audit of maybes gets ignored.
            target = value.func
            name = (target.id if isinstance(target, ast.Name)
                    else target.attr if isinstance(target, ast.Attribute) else "")
            helper = (local or {}).get(name)
            if helper is not None and depth < 2 and helper is not node:
                inner, inner_detail = _shape_of(helper, local, depth + 1)
                kinds.add(inner)
                detail = detail or inner_detail
            else:
                kinds.add("unknown")
        else:
            kinds.add("unknown")
    if not kinds:
        return "unknown", ""
    # A handler with one readable `return [...]` and one unreadable branch —
    # usually an early `return helper()` for the empty case — returns a list.
    # Left as "unknown" it would be one more line of noise in a report whose
    # only value is that people read all of it.
    if "list" in kinds and "dict" not in kinds:
        kinds.discard("unknown")
    if kinds == {"list"}:
        return "list", ""
    if kinds == {"dict"}:
        return "dict", detail
    if "list" in kinds and "dict" in kinds:
        return "mixed", detail
    if "list" in kinds:
        return "list", ""
    if "dict" in kinds:
        return "dict", detail
    return "unknown", ""


def backend_routes() -> dict[str, tuple[str, str, str]]:
    """path -> (shape, detail, where). Built from the routers themselves."""
    routes: dict[str, tuple[str, str, str]] = {}
    for file in sorted(ROUTERS.glob("*.py")):
        text = file.read_text(encoding="utf-8", errors="replace")
        prefix_match = re.search(
            r"""APIRouter\((?:[^)]*?)prefix\s*=\s*["']([^"']*)["']""", text, re.S)
        prefix = prefix_match.group(1) if prefix_match else ""
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue

        # Every function in the file, so a handler that returns `_rows(...)`
        # can be followed to where the shape is actually decided.
        local = {n.name: n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

        # Decorators carry the path; the function under them carries the shape.
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                if not (isinstance(func, ast.Attribute) and func.attr == "get"):
                    continue
                if not (isinstance(func.value, ast.Name)
                        and func.value.id.startswith("router")):
                    continue
                if not decorator.args or not isinstance(decorator.args[0], ast.Constant):
                    continue
                path = (prefix + decorator.args[0].value).rstrip("/") or prefix
                declared = _declared_shape(decorator)
                if declared:
                    shape, detail = declared, "declared by response_model"
                else:
                    shape, detail = _shape_of(node, local)
                routes[path] = (shape, detail,
                                f"{file.name}:{node.lineno} {node.name}")
    return routes


def main() -> int:
    show_all = "--all" in sys.argv
    routes = backend_routes()
    calls = frontend_calls()

    wrong: list[str] = []
    unsure = 0
    agree = 0

    print(f"  {len(calls)} place(s) assert an endpoint returns an array, "
          f"against {len(routes)} GET route(s)\n")

    for file, line, path, typed in calls:
        entry = routes.get(path)
        if entry is None:
            # A path with an id in it, or one served from a router this cannot
            # see. Not reported: an unmatched path is a gap in this script, not
            # evidence of a bug, and reporting it as one is how an audit starts
            # being ignored.
            continue
        shape, detail, where = entry
        rel = file.relative_to(ROOT).as_posix()
        if shape == "dict":
            wrong.append(
                f"{rel}:{line}\n"
                f"       asks for {typed} from {path}\n"
                f"       but {where} returns an object {detail or ''}".rstrip()
                + "\n       so anything iterating it throws "
                  "`.map is not a function` on that screen")
        elif shape in ("mixed", "unknown"):
            unsure += 1
            if show_all:
                print(f"  ?    {rel}:{line} {path} — {where} returns "
                      f"{shape}, not read further")
        else:
            agree += 1
            if show_all:
                print(f"  ok   {rel}:{line} {path}")

    if show_all:
        print()
    for report in wrong:
        print(f"  FAIL {report}\n")

    print(f"  {agree} agree, {unsure} could not be read from the return "
          f"statements alone, {len(wrong)} disagree")
    if wrong:
        print("\na screen iterating an object is a white page for whoever "
              "opens it, and nothing in the build says so")
        return 1
    print("\nevery screen that iterates a response asks an endpoint that "
          "returns a list")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
