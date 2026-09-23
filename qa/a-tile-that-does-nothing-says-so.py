"""A figure that is not a control must not look like one.

WHY THIS GUARD EXISTS

`.wl-stat` was written for the dispensary rail, where every tile filters the
queue, so it carried `cursor: pointer` and a hover state for all of them. The
tile then spread across the product as a neat way to show a figure, and a
sweep found 107 of them rendered as plain divs: 107 tiles that took the
pointer, lit up under it, and did nothing. Somebody presses two of those and
stops trying the rest, which is how a tile that IS a filter goes unused.

THE RULE

The element says whether it is a control. A tile that filters is a <button>;
a tile that reports is a <div>. So the affordance is attached to
`button.wl-stat` and `a.wl-stat` rather than to the class, and a new
reporting tile is inert by default rather than by somebody remembering.

This checks the stylesheet, not the pixels: that the bare class does not hand
out a pointer or a hover, and that the interactive forms still do. A
rendering sweep is in qa's browser checks; this is the cheap version that
runs without a server.
"""
import pathlib
import re
import sys

CSS = (pathlib.Path(__file__).resolve().parents[1]
       / "frontend" / "src" / "styles.css").read_text(encoding="utf-8")

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


def body(selector: str) -> str:
    """Every declaration block whose selector list contains this exactly."""
    out = []
    for sel, block in re.findall(r"([^{}]+)\{([^{}]*)\}", CSS):
        parts = [s.strip() for s in sel.split(",")]
        if selector in parts:
            out.append(block)
    return " ".join(out)


print("\n  a tile that does nothing says so\n")

bare = body(".wl-stat")
check("the tile class exists", bool(bare.strip()))

check("the bare class does not offer a pointer",
      "cursor: pointer" not in bare,
      ".wl-stat sets cursor: pointer, so every reporting tile in the product "
      "claims to be pressable")

hover_bare = body(".wl-stat:hover")
check("the bare class does not light up under the pointer",
      not hover_bare.strip(),
      ".wl-stat:hover exists, so a plain figure responds like a control")

# The other half: the real filters must keep their affordance.
interactive = body("button.wl-stat") + body("a.wl-stat")
check("a tile that IS a control still offers the pointer",
      "cursor: pointer" in interactive,
      "button.wl-stat has no pointer, so the dispensary rail's filters read "
      "as decoration")

hover_live = body("button.wl-stat:hover") + body("a.wl-stat:hover")
check("a tile that IS a control still responds to it",
      bool(hover_live.strip()),
      "no hover on button.wl-stat")

print(f"\n  {passed} passed, {failed} failed\n")
sys.exit(1 if failed else 0)
