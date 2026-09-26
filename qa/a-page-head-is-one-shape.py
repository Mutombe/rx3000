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

    A page that has adopted `<PageHead>` has no block to measure and no way to
    get these wrong: the component decides the element, the subtitle class and
    the action group. Those pages are counted as headers and skipped by the
    checks below, which is why the count is of ADOPTERS PLUS hand-rolled
    blocks rather than of blocks alone.

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
read = {p.name: p.read_text(encoding="utf-8") for p in pages}
# A page using the component is already one shape, by construction.
shared = sorted(n for n, t in read.items() if "<PageHead" in t)
heads = {n: head_of(t) for n, t in read.items() if n not in shared}
heads = {n: h for n, h in heads.items() if h}
check(f"there are page headers to check "
      f"({len(shared)} on the shared component, {len(heads)} hand-rolled)",
      len(shared) + len(heads) > 30)

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


# ---------------------------------------------------------------------------
# And the same three faults, INSIDE the shared component
# ---------------------------------------------------------------------------
#
# WHY THIS HALF WAS MISSING, AND WHAT GOT THROUGH BECAUSE OF IT.
#
# Everything above skips a page that uses `<PageHead>` on the grounds that the
# component decides its shape. That was true of the element and the subtitle
# and stopped being true the moment the component took `children`: nine pages
# passed a whole `<div className="page-actions">` of their own through it, so
# the rendered header had one flex row nested inside another and drew its gap
# from the inner one. Deliveries had that AND its slots filled, which is two
# action groups on one header, and every check above reported it as fine.
#
# `children` is gone from the component now, so TypeScript refuses the shape
# outright. This catches the version of it that TypeScript cannot see — a page
# passing the group through one of the four slots instead — and it reads the
# whole element rather than the six-space block, because a slot's markup is
# indented past anything `head_of` bounds.


def tag_end(text: str, start: int) -> tuple[int, bool]:
    """Where the opening `<PageHead ...>` tag ends, and whether it self-closes.

    Counted rather than searched for. A slot holds JSX, so the tag contains
    `>` and `/>` of its own — `<Plus size={14} />` inside a button inside
    `primary={...}` — and the first `/>` after the tag start belongs to a child
    a dozen times over. So this walks the braces: depth zero is the tag's own
    attribute list, and the `>` that matters is the one found there.

    Strings are skipped because an attribute value can hold either character,
    and a page does write `placeholder="Reports…"` and `sub="...>..."`.
    """
    i, depth = start + len("<PageHead"), 0
    while i < len(text):
        two = text[i:i + 2]
        # Comments first. Every header in this product carries its reasoning,
        # and that prose is full of apostrophes — "the header's cascade",
        # "a debtors' list" — each of which would open a string that never
        # closes and send this walking to the end of the file.
        if two == "/*":
            i = text.find("*/", i)
            if i == -1:
                return len(text), False
            i += 2
            continue
        if two == "//":
            i = text.find("\n", i)
            if i == -1:
                return len(text), False
            continue
        c = text[i]
        if c in "\"'`":
            i += 1
            while i < len(text) and text[i] != c:
                i += 2 if text[i] == "\\" else 1
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif depth == 0 and c == ">":
            return i + 1, text[i - 1] == "/"
        i += 1
    return len(text), False


def heads_of(text: str) -> list[str]:
    """Every `<PageHead ...>` element in a file, opening tag to close.

    A self-closing one ends where its tag ends; one with children ends at its
    own `</PageHead>`. Two pages open a header in an early return and another
    in the ordinary path, so each is measured from its own start.
    """
    out = []
    for m in re.finditer(r"<PageHead\b", text):
        end, closed = tag_end(text, m.start())
        if closed:
            out.append(text[m.start():end])
        else:
            shut = text.find("</PageHead>", end)
            out.append(text[m.start(): shut if shut != -1 else end])
    return out


slotted = {n: heads_of(t) for n, t in read.items() if "<PageHead" in t}
GROUPS = re.compile(r'className="(?:page-actions|row-actions|toolbar|ax-page-acts)"')
nested = sorted({n for n, blocks in slotted.items()
                 for b in blocks if GROUPS.search(b)})
check("no page passes its own action group through the component", not nested,
      "PageHead already renders .page-actions; a second one inside it nests "
      "one flex row in another and the spacing stops matching: "
      + ", ".join(nested))

# A page that fills no slot at all is not a fault — Profile and Fiscal have
# nothing to offer up there and an invented button would be worse. A page that
# fills them in the wrong ORDER is invisible on screen, because the component
# renders them in its own order whatever order they are written in, so there is
# nothing to check there either.
filled = sorted(n for n, blocks in slotted.items()
                for b in blocks if re.search(r"\b(bring|take|also|primary)=", b))
check(f"the slots are being used ({len(filled)} pages fill at least one)",
      len(filled) > 30)

print(f"\n  {passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
