"""A class name must mean one thing.

WHAT WENT WRONG

`.lbl` was the 58mm x 42mm sticker a patient takes home with their medicine:
a width, a minimum height, a padding, a white fill and a border. Somebody
later wanted a small uppercase heading over a group of form controls, reached
for the obvious short name, and wrote a second `.lbl` eight thousand lines
further down the same stylesheet.

Two rules for one class is not a draw, and that is the part that makes this
worth a guard. The later rule wins only on the properties it happens to
mention. Everything it leaves out is still supplied by the earlier one. So
the heading kept the sticker's width, minimum height, padding, fill and
border, and three words rendered inside an empty bordered box 219 pixels wide
and 159 tall, on quotation screens that had already shipped.

Nothing catches this. It is not a dead class, so `dead-classes` is happy. It
is not an inherited colour, so `inherited-colour` is happy. Both rules are
used, both are valid CSS, and the page is simply wrong.

WHAT THIS ALLOWS

Repeating a class deliberately is ordinary and fine:

  a state or a variant             .btn.primary, .row.is-muted
  a media query or a theme block   the same selector under a breakpoint
  a pseudo class                   .btn:hover, .field:focus-within

So a plain duplicate of a BARE single class selector is what is reported, and
only when both blocks set something about the box: width, height, padding,
border, background or display. Two rules that between them set a colour and a
font size are somebody splitting a component up, which is untidy and harmless.

AND ONLY WHEN THEY ARE FAR APART

This is the discriminator that makes the list short enough to act on. A base
rule and its variant sit together:

    .sc-pulse, .sc-wait { width: 8px; height: 8px; border: ... }
    .sc-pulse { background: var(--ok); }
    .sc-wait  { background: var(--warn); }

Three lines apart, one author, one component, entirely deliberate. The
collision this guard exists for is between two people who never met: `.lbl`
was eight thousand lines from `.lbl`. So a second rule within NEARBY lines of
the first is taken as the same person still writing the same component, and
the count of those is reported without naming them.

HOW TO FIX ONE

Rename, do not patch. Adding the missing properties to the later rule leaves
the collision in place, and the next person to add a property to the first
one breaks the second again with no way of knowing they have.
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHEETS = sorted((ROOT / "frontend" / "src").rglob("*.css"))

#: Properties that decide the shape of the box. Two rules disagreeing about a
#: colour is untidy; two rules disagreeing about these is a broken screen.
SHAPE = ("width", "height", "min-height", "min-width", "max-height",
         "padding", "border", "background", "display")

#: Two rules closer together than this are one author still writing one
#: component: a base rule and the variants under it. Farther apart than this
#: and they were written months apart by people who did not know about each
#: other, which is where this goes wrong.
NEARBY = 1000

#: A bare single class and nothing else: `.lbl {`, not `.lbl.on`, `.a .b`,
#: `.btn:hover` or `.card > p`.
BARE = re.compile(r"^\.([A-Za-z_][\w-]*)$")

#: Comments first, so a `{` inside one cannot be read as the start of a rule.
COMMENTS = re.compile(r"/\*.*?\*/", re.S)


def blocks(css: str):
    """Every top level `selector { body }`, with the line it starts on."""
    css = COMMENTS.sub(lambda m: "\n" * m.group().count("\n"), css)
    depth, start, at_depth = 0, 0, []
    out = []
    i = 0
    while i < len(css):
        char = css[i]
        if char == "{":
            if depth == 0:
                selector = css[start:i].strip()
                at_depth.append((selector, i + 1))
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0 and at_depth:
                selector, body_at = at_depth.pop()
                body = css[body_at:i]
                # A media or supports block holds rules rather than
                # declarations; those are variants of the same component and
                # are exactly what this guard must not report.
                if not selector.startswith("@"):
                    line = css.count("\n", 0, body_at) + 1
                    out.append((selector, body, line))
                start = i + 1
        i += 1
    return out


def shape_of(body: str) -> set[str]:
    found = set()
    for declaration in body.split(";"):
        name = declaration.split(":", 1)[0].strip().lower()
        if not name:
            continue
        for prop in SHAPE:
            if name == prop or name.startswith(prop + "-"):
                found.add(prop)
    return found


def main() -> int:
    seen: dict[str, list] = defaultdict(list)
    for sheet in SHEETS:
        for selector, body, line in blocks(sheet.read_text(encoding="utf-8")):
            for one in selector.split(","):
                match = BARE.match(one.strip())
                if match:
                    seen[match.group(1)].append(
                        (sheet.relative_to(ROOT), line, shape_of(body)))

    clashes, together = [], 0
    for name, uses in sorted(seen.items()):
        shaped = [u for u in uses if u[2]]
        if len(shaped) < 2:
            continue
        # Far apart in the same sheet, or in different sheets entirely:
        # either way the two authors did not know about each other.
        apart = any(a[0] != b[0] or abs(a[1] - b[1]) > NEARBY
                    for a in shaped for b in shaped)
        if apart:
            clashes.append((name, shaped))
        else:
            together += 1

    print("one class, one meaning")
    print()
    if not clashes:
        print(f"  ok   {len(seen)} bare class rule(s) read; none is shaped "
              "twice from far apart")
        if together:
            print(f"  ok   {together} shaped more than once nearby, which is "
                  "a base rule and its variants")
        print()
        print("a class that means two things renders as neither")
        return 0

    for name, uses in clashes:
        print(f"  X    .{name}")
        for path, line, shape in uses:
            print(f"       {path}:{line}  sets {', '.join(sorted(shape))}")
        print("       two unrelated components answer to this name. The later "
              "rule wins")
        print("       only on what it mentions; the rest comes from the other "
              "one. Rename")
        print("       one of them rather than patching in the missing "
              "properties.")
        print()

    if together:
        print(f"  ({together} more are shaped twice within {NEARBY} lines, "
              "which is a base rule")
        print("   and its variants, and is not what this looks for.)")
        print()
    print(f"  {len(clashes)} class name(s) mean two things")
    return 1


if __name__ == "__main__":
    sys.exit(main())
