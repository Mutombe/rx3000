"""Is anything wearing a class the stylesheet has never heard of?

The churn summary rendered as

    Churn4.7%7 of 148 regulars stopped coming

— three separate facts run into one string with nothing between them, on the
screen a manager opens to decide who to telephone. Nothing had broken. The
markup asked for `.wc-band` and `.wc-band-label`, and **neither class existed
anywhere in the stylesheet**, so the browser did exactly what it was told: it
laid out three inline elements in a row. The chart of accounts used the same
two names and was wrong in the same way.

This is a peculiarly quiet fault. A missing rule is not an error in any tool:
it type-checks, it builds, it renders, and the only way to find it is to look
at the page. A class name is a string, and a string that matches nothing looks
exactly like a string that matches something.

WHAT IT SKIPS, AND WHY THAT IS NOT A LOOPHOLE

Only literal class names are read. A name built by interpolation — `tone-${x}`,
`is-${on}`: cannot be resolved without running the code, and guessing would
produce exactly the kind of false alarm that gets an audit ignored. Utility
names the sheet declares in bulk are matched by the same literal search, so
they need no exception.

A class used in one place and styled nowhere is reported. A class styled
somewhere and used nowhere is not: dead CSS is untidy, not broken, and mixing
the two would bury the fault that matters in a list of the fault that does not.

    python qa/dead-classes.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"

SHEETS = [SRC / "styles.css", SRC / "portal" / "portal.css"]

#: Names that are markers rather than styling: read by code, matched by a
#: selector built at runtime, or handed to a library.
IGNORE = {
    # Test and automation hooks.
    "no-print", "print-only",
    # Naming hooks that are deliberately unstyled. Each is written beside a
    # class that does the work, and exists so the markup says what the thing is
    # rather than only how it looks. Listed explicitly, with a reason, because
    # the alternative, leaving them in the report for ever, is a check that
    # always fails and therefore never gets read.
    "page",       # every page's outermost wrapper; the layout is on `.main`
    "accent",     # a modifier on `.value`, kept for meaning
    "keymap",     # a modifier on `.modal`, sized inline
    "su-error",   # a modifier on `.alert error`
    "panel",      # a modifier on `.counter-messages`
    "sk-tabs",    # a skeleton shape, sized by its children
}


def styled() -> set[str]:
    """Every class the stylesheets mention, anywhere in any selector."""
    out: set[str] = set()
    for sheet in SHEETS:
        if not sheet.exists():
            continue
        css = re.sub(r'/\*.*?\*/', ' ',
                     sheet.read_text(encoding="utf-8", errors="replace"),
                     flags=re.S)
        # Selectors only — a class name appearing inside a declaration (in a
        # `content:` string, say) is not a rule.
        for selector in re.findall(r'([^{}]+)\{', css):
            out.update(re.findall(r'\.([A-Za-z][\w-]*)', selector))
    return out


def used() -> dict[str, list[str]]:
    """Literal class names in the components, and where each is written."""
    found: dict[str, list[str]] = {}
    for file in sorted(SRC.rglob("*.tsx")):
        text = file.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r'className=(\{?)(["`\'])(.*?)\2', text, re.S):
            value = match.group(3)
            # Anything with an interpolation or an expression in it is not a
            # literal, and the parts around the hole are not reliably whole
            # class names either.
            if "${" in value or (match.group(1) and "?" in value):
                continue
            line = text.count("\n", 0, match.start()) + 1
            for name in value.split():
                if not re.fullmatch(r'[a-z][\w-]*', name) or name in IGNORE:
                    continue
                where = f"frontend/src/{file.relative_to(SRC).as_posix()}:{line}"
                found.setdefault(name, [])
                if where not in found[name]:
                    found[name].append(where)
    return found


def main() -> int:
    have = styled()
    if not have:
        print("  no stylesheet found")
        return 2

    wanted = used()
    dead = {n: w for n, w in wanted.items() if n not in have}

    for name in sorted(dead, key=lambda n: -len(dead[n])):
        places = dead[name]
        print(f"  X    .{name}\n"
              f"       asked for by the markup and styled nowhere, so it does "
              f"nothing at all.\n"
              f"       Used at: {', '.join(places[:3])}"
              + (f" and {len(places) - 3} more" if len(places) > 3 else "")
              + "\n")

    print(f"  {len(wanted)} literal class(es) in use against {len(have)} "
          f"styled; {len(dead)} have no rule")
    if dead:
        print("\na class that matches nothing looks exactly like a class that "
              "matches something — until somebody looks at the page.")
        return 1
    print("\nevery class the markup asks for exists in the stylesheet")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
