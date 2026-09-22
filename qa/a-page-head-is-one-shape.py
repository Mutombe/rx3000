"""Every page header is built the same way.

WHY THIS GUARD EXISTS

Measured across the list pages before any of this: header heights of 52, 62,
66, 72, 76, 101, 130 and 176 pixels. Eight shapes for one thing. The causes
were all structural rather than a matter of taste:

  * Two classes meant the same thing. Forty pages wrote the subtitle as
    `<div className="sub">` and eighteen as `<p className="muted">`, which
    keeps the browser's default paragraph margins — about 16px above AND
    below — and the inherited type size, so those headers were taller and
    spaced differently for no reason anybody chose.

  * Nine pages put their family navigation in the action slot. On
    Authorisations a tab strip, a search box and a primary button shared one
    corner and wrapped the header to 176px. Navigation is not an action, and
    a search belongs with the rows it narrows.

  * Five pages hand-rolled the action group with an inline flex style instead
    of `.page-actions`, which is five places to change when the spacing moves
    and one of them always gets missed.

WHAT IS DELIBERATELY ALLOWED

A control that scopes the WHOLE page — "Last 90 days" on a performance
report — belongs in the header. A control that filters one table does not.
That distinction is a judgement this cannot make, so it checks the three
things above, which are not judgements.
"""
import pathlib
import re
import sys

PAGES = pathlib.Path(__file__).resolve().parents[1] / "frontend" / "src" / "pages"

passed = failed = 0


def check(said, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  ok   {said}")
    else:
        failed += 1
        print(f"  X    {said}")
        if detail:
            print(f"       {detail}")


def head_of(text: str) -> str | None:
    """The header block, bounded by its OWN indentation.

    An earlier version looked for the first `\\n      </div>` at six spaces.
    Dispensing opens its header at eight, so the block ran past the header and
    swallowed the card beneath it: the guard then reported a paragraph in an
    empty state as a malformed subtitle. A regex that guesses the indentation
    of the thing it is measuring reports faults that are not there, and a
    guard that cries wolf is one nobody reads.
    """
    m = re.search(r'^([ \t]*)<(?:div|header) className=\{?[`"]page-head',
                  text, re.M)
    if not m:
        return None
    indent = m.group(1)
    rest = text[m.start():]
    end = re.search(rf"\n{indent}</(?:div|header)>\n", rest)
    return rest[: end.end()] if end else rest[:4000]


print("\n  every page header is one shape\n")

pages = sorted(PAGES.glob("*.tsx"))
heads = {p.name: head_of(p.read_text(encoding="utf-8")) for p in pages}
heads = {n: h for n, h in heads.items() if h}
check(f"there are page headers to check ({len(heads)})", len(heads) > 30)

muted = [n for n, h in heads.items() if '<p className="muted"' in h]
check("the subtitle is written one way", not muted,
      "a <p className=\"muted\"> subtitle keeps the browser's paragraph "
      "margins and inherited size, so the header is a different height: "
      + ", ".join(muted))

navs = [n for n, h in heads.items() if "<SectionNav" in h or "<PageTabs" in h]
check("no header holds navigation in its action slot", not navs,
      "navigation is not an action, and it wraps the header: " + ", ".join(navs))

inline = [n for n, h in heads.items() if 'style={{ display: "flex"' in h]
check("no header hand-rolls its action group", not inline,
      'use .page-actions rather than an inline flex style: ' + ", ".join(inline))

print(f"\n  {passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
