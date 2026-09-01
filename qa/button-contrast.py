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
somebody opens that exact panel, which for the allergy picker meant it shipped.

So: find every class used on a `<button>`, and report the ones whose rule sets
a text colour with no background of their own. Inheriting is not a neutral
default here; it is the accent fill.

THE SAME FAULT INVERTED

There is a second way to get this wrong, and this check walked past it for
months. `.linkish` — a button that reads as a link inside a sentence — set
`background: none` and kept `color: var(--accent-ink)`. That token is the ink
for text sitting ON the accent: white in light mode, near-black in dark. With
the fill removed it landed on the ordinary surface, so the control was white on
white by day and black on black by night. Invisible in both themes, which is
why it was never reported as a colour problem: the Undo in the sig expander
simply looked like it had not been built.

So both directions are read now — an ink with no fill under it, and a fill
removed with the on-fill ink kept.

WHAT IT DOES NOT FLAG

Variant and size modifiers, `.primary`, `.danger`, `.sm`, are applied
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


def button_uses() -> list[tuple[str, set[str]]]:
    """Every `<button>` as (where, the classes on it together).

    Together, because a class is only in trouble when nothing else on the same
    button supplies a background. `.term-add` sets an accent text colour and no
    fill, which read as accent-on-accent until you notice it is always written
    as `term-option term-add`, and `.term-option` is the one carrying the
    transparent background. Read one class at a time, that is a failure; read as
    the button actually renders, it is a modifier doing its job.
    """
    out: list[tuple[str, set[str]]] = []
    for file in sorted(FRONTEND.rglob("*.tsx")):
        text = file.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(
                r'<button\b[^>]{0,500}?className=\{?[`"\']([^`"\']*)', text, re.S):
            line = text.count("\n", 0, match.start()) + 1
            # Only the literal text of the template, never what is inside
            # `${…}`. `` `term-option${highlight >= shown.length ? …}` ``
            # otherwise yields "highlight", "shown" and "length" as classes,
            # and `.highlight` is a real class with a background, so the very
            # bug this file was written for read as covered by a companion that
            # is a JavaScript variable.
            literal = re.sub(r'\$\{[^}]*\}', ' ', match.group(1))
            # And the truncated case, which is the common one: the capture
            # stops at the first quote, and in
            # `` `term-option${n === highlight ? " is-on" : ""}` `` that quote
            # is inside the expression, so the text ends mid-`${`, with the
            # closing brace never reached. Everything after an unclosed `${`
            # is expression, not classes.
            literal = re.sub(r'\$\{.*', ' ', literal, flags=re.S)
            classes = set(re.findall(r'[a-z][a-z0-9-]+', literal))
            if classes:
                out.append((f"{file.relative_to(ROOT).as_posix()}:{line}",
                            classes))
    return out


def button_classes() -> dict[str, list[str]]:
    """Every class that appears on a `<button>`, and where."""
    found: dict[str, list[str]] = {}
    for where, classes in button_uses():
        for cls in classes:
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
    # Comments out first. Without this a rule preceded by a comment is read as
    # having a selector of `/* … */ .thing`, which matches nothing, and the
    # class drops out of the audit silently — it reads as "no rule of its own"
    # rather than as an error. Writing a note above `.linkish` was enough to
    # make this check stop seeing the very class it was about to catch.
    css = re.sub(r'/\*.*?\*/', ' ',
                 CSS.read_text(encoding="utf-8", errors="replace"), flags=re.S)
    out: dict[str, dict] = {}
    for selector, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
        bg = re.search(r'(?:^|[;\s])background(?:-color)?\s*:\s*([^;]+)', body)
        has_bg = bool(bg)
        # `background: none` is not a background. A class that removes the fill
        # and keeps the on-fill ink is the same failure inverted, and the
        # earlier version read the removal as coverage.
        stripped = bool(bg) and bg.group(1).strip().lower() in {
            "none", "transparent", "0", "initial", "unset"}
        colour = re.search(r'(?:^|[;\s])color\s*:\s*([^;]+)', body)
        for part in (p.strip() for p in selector.split(",")):
            bare = re.fullmatch(r'\.([a-z][a-z0-9-]+)', part)
            if not bare:
                continue
            entry = out.setdefault(bare.group(1),
                                   {"bg": False, "stripped": False,
                                    "colour": None, "line": 0})
            if has_bg:
                entry["bg"] = True
            if stripped:
                entry["stripped"] = True
            if colour and entry["colour"] is None:
                # `var(--accent-ink, inherit)` is the same token as
                # `var(--accent-ink)`; the fallback only applies if it is
                # undefined, and it is defined. Comparing the raw text meant
                # the one class this check was extended for did not match the
                # list it was extended against.
                text = colour.group(1).strip().lower()
                entry["colour"] = re.sub(r'var\(\s*(--[\w-]+)\s*,[^)]*\)',
                                         r'var(\1)', text)
    return out


def main() -> int:
    show_all = "--all" in sys.argv
    used = button_classes()
    declared = rules()

    bad: list[str] = []
    checked = 0

    # Which classes are always written beside one that supplies a real fill.
    # A modifier is doing its job there; only a class that is ever rendered
    # without such a companion can land its ink on the base button's accent.
    #
    # `background: transparent` counts here. It is an explicit opt-out of the
    # base fill, so whatever panel is behind shows through, which is what
    # `.term-option` was changed to, and why `.term-add` beside it is fine. It
    # is a different question from whether a class strips the fill and then
    # keeps the ink meant to sit on it; that is the case just above.
    #
    # And a class is never its own companion, or `.linkish`, which sets
    # `background: none` and is written alone — would excuse itself.
    alone: dict[str, bool] = {}
    for _, classes in button_uses():
        for cls in classes:
            companion = any(declared.get(c, {}).get("bg")
                            for c in classes if c != cls)
            alone[cls] = alone.get(cls, False) or not companion

    for cls in sorted(used):
        rule = declared.get(cls)
        if rule is None:
            continue
        checked += 1
        colour = rule["colour"]
        if show_all:
            print(f"  .{cls:<20} background {'yes' if rule['bg'] else 'NO ':<4} "
                  f"colour {colour or '—'}")
        if colour is None:
            continue
        if not alone.get(cls, True):
            continue          # never rendered without something under it
        # The inverse case, and the one this check first walked past.
        # `.linkish` sets `background: none` and `color: var(--accent-ink)` —
        # the ink meant for text sitting ON the accent, painted onto the
        # ordinary surface instead. White on white in light mode, near-black on
        # near-black in dark: invisible in both, which is why it was never
        # reported as a colour problem. The Undo in the sig expander simply
        # looked like it was not there.
        # `inherit` and `currentcolor` are not on-accent tokens — they take
        # whatever the surrounding text is, which is the right answer once the
        # fill is gone. Only the tokens that name a specific ink for the accent
        # are wrong here.
        if rule["stripped"] and colour in SAFE_ON_ACCENT - {"inherit",
                                                            "currentcolor"}:
            bad.append(
                f".{cls}\n"
                f"       removes the fill (`background: none`) and keeps\n"
                f"       `color: {colour}` — the ink for text ON the accent,\n"
                f"       painted onto the ordinary surface. Invisible in both\n"
                f"       themes, because the token inverts with them.\n"
                f"       Used at: {', '.join(used[cls][:3])}")
            continue
        if rule["bg"] or colour in SAFE_ON_ACCENT:
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
          f"{len(bad)} paint an ink onto a fill it was not meant for")
    if bad:
        print("\na control that is a button for keyboard reasons still has to "
              "declare its own background — inheriting gives it the primary fill")
        return 1
    print("\nevery button-shaped control declares the background it sits on")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
