"""Is any button-shaped control painting dark text on the dark accent fill?

The allergies picker rendered every option as near-black text on a near-black
background. Only the row under the pointer was readable, because that one got
`--hover`. This was on the field whose entire purpose is to fire a blocking
safety warning at dispensing.

Nothing was wrong with the option's own styling. The cause is one line near the
top of the stylesheet:

    button, .btn { background: var(--accent); color: var(--accent-ink); }

Every `<button>` in the application is filled with the accent colour by
default. A control that is a button for keyboard and screen-reader reasons —
an option in a listbox, a row in a panel, a toggle — is not meant to look like
one, and if it declares `color` without also declaring `background`, it gets
its own ink on the primary fill. The two are near-identical, so it reads as a
solid dark block.

That is a silent failure. It type-checks, it builds, and it is invisible until
somebody opens that exact panel — which for the allergy picker meant it shipped.

So: find every class used on a `<button>`, and report the ones whose rule sets
a text colour with no background of their own. Inheriting is not a neutral
default here; it is the accent fill.

WHAT IT DOES NOT FLAG

Variant and size modifiers — `.primary`, `.danger`, `.sm` — are applied
alongside `.btn` and are *meant* to inherit or override the fill. They are only
reported when they set a text colour that would sit on the accent, which is the
actual failure. A check that listed every modifier would be a list of 60 lines
nobody reads, and an audit nobody reads is worse than no audit.

    python qa/button-contrast.py
    python qa/button-contrast.py --all     every class, with what it declares
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend" / "src"
CSS = FRONTEND / "styles.css"

#: Colours that are legible on the accent fill, so declaring them is fine.
#: `--accent-ink` is the fill's own text colour; white and the inverse tokens
#: are the same idea spelled differently.
SAFE_ON_ACCENT = {
    "var(--accent-ink)", "var(--surface)", "var(--ink-inverse)",
    "#fff", "#ffffff", "white", "inherit", "currentcolor",
}


def button_classes() -> dict[str, list[str]]:
    """Every class that appears on a `<button>`, and where."""
    found: dict[str, list[str]] = {}
    for file in sorted(FRONTEND.rglob("*.tsx")):
        text = file.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(
                r'<button\b[^>]{0,500}?className=\{?[`"\']([^`"\']*)', text, re.S):
            line = text.count("\n", 0, match.start()) + 1
            for cls in re.findall(r'[a-z][a-z0-9-]+', match.group(1)):
                where = f"{file.relative_to(ROOT).as_posix()}:{line}"
                found.setdefault(cls, [])
                if where not in found[cls]:
                    found[cls].append(where)
    return found


def rules() -> dict[str, dict]:
    """What each class declares in its own unqualified rule.

    Only the bare `.thing { }` selector counts for the background. A background
    on `.thing.is-on` or `.thing:hover` is the whole bug: the row is readable
    under the pointer and unreadable everywhere else, which is exactly how this
    survived being looked at.
    """
    css = CSS.read_text(encoding="utf-8", errors="replace")
    out: dict[str, dict] = {}
    for selector, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
        has_bg = bool(re.search(r'(?:^|[;\s])background(?:-color)?\s*:', body))
        colour = re.search(r'(?:^|[;\s])color\s*:\s*([^;]+)', body)
        for part in (p.strip() for p in selector.split(",")):
            bare = re.fullmatch(r'\.([a-z][a-z0-9-]+)', part)
            if not bare:
                continue
            entry = out.setdefault(bare.group(1),
                                   {"bg": False, "colour": None, "line": 0})
            if has_bg:
                entry["bg"] = True
            if colour and entry["colour"] is None:
                entry["colour"] = colour.group(1).strip().lower()
    return out


def main() -> int:
    show_all = "--all" in sys.argv
    used = button_classes()
    declared = rules()

    bad: list[str] = []
    checked = 0

    for cls in sorted(used):
        rule = declared.get(cls)
        if rule is None:
            continue
        checked += 1
        colour = rule["colour"]
        if show_all:
            print(f"  .{cls:<20} background {'yes' if rule['bg'] else 'NO ':<4} "
                  f"colour {colour or '—'}")
        if rule["bg"] or colour is None:
            continue
        if colour in SAFE_ON_ACCENT:
            continue
        bad.append(
            f".{cls}\n"
            f"       sets `color: {colour}` and no background of its own, so it\n"
            f"       inherits `background: var(--accent)` from the base button\n"
            f"       rule — dark text on the dark accent fill.\n"
            f"       Used at: {', '.join(used[cls][:3])}"
            + (f" and {len(used[cls]) - 3} more" if len(used[cls]) > 3 else ""))

    if show_all:
        print()
    for report in bad:
        print(f"  FAIL {report}\n")

    print(f"  {checked} button class(es) have a rule of their own; "
          f"{len(bad)} paint their own ink on the accent fill")
    if bad:
        print("\na control that is a button for keyboard reasons still has to "
              "declare its own background — inheriting gives it the primary fill")
        return 1
    print("\nevery button-shaped control declares the background it sits on")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
