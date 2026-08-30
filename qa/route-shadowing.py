"""Routes that can never be reached, because a parameterised one ate them.

FastAPI matches in registration order. `/{id}/users` declared before
`/unassigned/users` means "unassigned" is handed to the first route as an id,
and the answer is a 422 about integer parsing rather than the list somebody
asked for.

Nothing catches this. The endpoint exists, its tests pass when called directly,
and the screen that uses it fails quietly in a way that reads as "there is
nothing here". One of these was live: the platform-admin list of users
belonging to no pharmacy — the one list whose entire purpose is to notice
people who would otherwise sign in and see an empty system.

Run: python qa/route-shadowing.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTERS = ROOT / "backend" / "app" / "routers"

DECL = re.compile(r'@router\.(get|post|put|patch|delete)\(\s*"([^"]*)"')
PARAM = re.compile(r"\{[^}]+\}")


def segments(path: str) -> list[str]:
    return [s for s in path.strip("/").split("/") if s]


def shadows(earlier: list[str], later: list[str]) -> bool:
    """Would a request for `later` be matched by `earlier` instead?

    Only when they are the same length and every segment of the earlier route
    either equals the later one or is a parameter standing where the later
    route has a literal.
    """
    if len(earlier) != len(later):
        return False
    took_a_literal = False
    for a, b in zip(earlier, later):
        if a == b:
            continue
        if PARAM.fullmatch(a) and not PARAM.fullmatch(b):
            took_a_literal = True
            continue
        return False
    return took_a_literal


def main() -> int:
    findings: list[str] = []
    for path in sorted(ROUTERS.glob("*_router.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        routes: list[tuple[int, str, str, list[str]]] = []
        for m in DECL.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            routes.append((line, m.group(1), m.group(2), segments(m.group(2))))

        for i, (line, verb, route, segs) in enumerate(routes):
            for earlier_line, earlier_verb, earlier_route, earlier_segs in routes[:i]:
                if earlier_verb != verb:
                    continue
                if shadows(earlier_segs, segs):
                    findings.append(
                        f"  {path.name}:{line}\n"
                        f"      {verb.upper():<6} {route or '/'}\n"
                        f"      is unreachable — {earlier_route or '/'} at line "
                        f"{earlier_line} matches it first")
                    break

    if findings:
        print("Routes shadowed by an earlier parameterised route\n")
        print("\n".join(findings))
        print(f"\n{len(findings)} unreachable route(s). Move each one ABOVE the "
              f"route that shadows it.")
        return 1

    print("0 routes shadowed by an earlier parameterised one")
    return 0


if __name__ == "__main__":
    sys.exit(main())
