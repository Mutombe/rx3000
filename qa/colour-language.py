"""Do the four colours still tell each other apart?

The product uses colour to say what a thing IS: navy for a person, violet for a
script, raspberry for a medicine, bronze for money. That only works if a
dispenser can tell them apart at a glance, on their monitor, with their eyes —
and colour is the one part of an interface that can be badly wrong while
looking perfectly fine to whoever chose it.

WHAT THIS MEASURES

Every pair, in both themes, three ways:

  the distance in OKLab, which is perceptually uniform, so the number means
    the same thing at every lightness;
  the same distance through a deuteranopia simulation;
  and through a protanopia simulation.

Roughly one man in twelve has one of those. A palette that only separates by
hue collapses for them, which is why the four differ in lightness as well.

WHY IT IS A CHECK AND NOT A NOTE

The first four hues were chosen by eye and were wrong. Person and money came
out 1.4 apart under protanopia, which is to say the same colour. They looked
fine on the monitor they were picked on. Nothing but measurement would have
caught it, and nothing but a check will catch the next edit that reaches for a
nicer blue.

It also asserts each colour against the four STATE colours — ok, warn, danger
and the controlled-substance wine — because those mean something too, and an
entity that drifts into looking like a warning is worse than one nobody has an
instinct about.

    python qa/colour-language.py
"""
from __future__ import annotations

import itertools
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHEET = ROOT / "frontend" / "src" / "styles.css"
TONE = ROOT / "frontend" / "src" / "entityTone.ts"
ROUTES = ROOT / "frontend" / "src" / "entityRoutes.ts"

#: Distances below these are reported. 8 is comfortable; 6 is the floor for a
#: reader with a colour vision deficiency, where a second cue (the label beside
#: it) is doing some of the work.
MIN_NORMAL = 8.0
MIN_CVD = 6.0

FAMILIES = ("person", "script", "medicine", "money")
STATES = ("controlled", "ok", "warn", "danger")


def lin(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def oklab(h: str) -> tuple[float, float, float]:
    r, g, b = (lin(v) for v in rgb(h))
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l, m, s = (v ** (1 / 3) if v > 0 else -((-v) ** (1 / 3)) for v in (l, m, s))
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def distance(a: str, b: str) -> float:
    la, aa, ba = oklab(a)
    lb, ab, bb = oklab(b)
    return round(math.dist((la * 100, aa * 100, ba * 100),
                           (lb * 100, ab * 100, bb * 100)), 1)


def simulate(h: str, kind: str) -> str:
    r, g, b = (lin(v) for v in rgb(h))
    if kind == "deuteranopia":
        r2, g2, b2 = (0.625 * r + 0.375 * g,
                      0.700 * r + 0.300 * g,
                      0.300 * g + 0.700 * b)
    else:
        r2, g2, b2 = (0.567 * r + 0.433 * g,
                      0.558 * r + 0.442 * g,
                      0.242 * g + 0.758 * b)

    def back(v: float) -> int:
        v = max(0.0, min(1.0, v))
        v = 12.92 * v if v <= 0.0031308 else 1.055 * v ** (1 / 2.4) - 0.055
        return round(v * 255)

    return "#%02x%02x%02x" % (back(r2), back(g2), back(b2))


def contrast(a: str, b: str) -> float:
    def lum(h):
        r, g, b_ = (lin(v) for v in rgb(h))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b_
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return round((hi + 0.05) / (lo + 0.05), 2)


def read_block(css: str, start: str) -> dict[str, str]:
    """The literal hex values declared in one theme block."""
    i = css.index(start)
    j = css.index("}", i)
    out = {}
    for name, value in re.findall(r'--([\w-]+)\s*:\s*(#[0-9a-fA-F]{3,8})\s*;',
                                  css[i:j]):
        out[name] = value
    return out


def main() -> int:
    css = SHEET.read_text(encoding="utf-8")
    failures: list[str] = []
    checked = 0

    def check(ok: bool, said: str, why: str = "") -> None:
        print(f"  {'ok  ' if ok else 'FAIL'} {said}")
        if not ok:
            failures.append(why or said)

    # Every linkable record must have been given a family.
    kinds = set(re.findall(r'^\s{2}([a-z_]+):\s*\(id: Id\)',
                           ROUTES.read_text(encoding="utf-8"), re.M))
    mapped = set(re.findall(r'^\s{2}([a-z_]+):\s*"(?:person|script|medicine|money)"',
                            TONE.read_text(encoding="utf-8"), re.M))
    missing = kinds - mapped
    check(not missing,
          f"all {len(kinds)} linkable record types have a colour",
          f"no colour for: {', '.join(sorted(missing))}. An unmapped record "
          f"renders in the default ink, which reads as 'not important' rather "
          f"than as 'nobody decided'")

    for theme, marker, surface in (
        ("light", ":root {", "#ffffff"),
        ("dark", ':root[data-theme="dark"] {', "#191920"),
    ):
        block = read_block(css, marker)
        palette = {}
        for name in FAMILIES:
            if f"e-{name}" in block:
                palette[name] = block[f"e-{name}"]
        for name in STATES:
            key = "sched" if name == "controlled" else name
            if key in block:
                palette[name] = block[key]

        if len(palette) < len(FAMILIES):
            check(False, f"{theme}: the four colours are declared",
                  f"{theme}: only found {sorted(palette)}")
            continue

        print(f"\n  {theme}")
        for name in FAMILIES:
            ratio = contrast(palette[name], surface)
            checked += 1
            check(ratio >= 4.5,
                  f"    {name:<9} {palette[name]}  contrast {ratio}",
                  f"{theme}: {name} is {ratio}:1 on the card, under the 4.5 "
                  f"needed for text somebody has to read")

        for a, b in itertools.combinations(palette, 2):
            if a not in FAMILIES and b not in FAMILIES:
                continue          # two state colours: not this check's business
            normal = distance(palette[a], palette[b])
            worst = min(distance(simulate(palette[a], k), simulate(palette[b], k))
                        for k in ("deuteranopia", "protanopia"))
            checked += 1
            if normal < MIN_NORMAL or worst < MIN_CVD:
                check(False,
                      f"    {a} vs {b}: normal {normal}, colour-blind {worst}",
                      f"{theme}: {a} and {b} are {normal} apart normally and "
                      f"{worst} apart to a colour-blind reader. Below "
                      f"{MIN_CVD} they are the same colour, and the whole "
                      f"point of the language is that they are not")

        print(f"    every pair separated (worst normal "
              f"{min(distance(palette[a], palette[b]) for a, b in itertools.combinations(palette, 2) if a in FAMILIES or b in FAMILIES)})")

    print()
    if failures:
        for f in failures:
            print(f"  {f}")
        return 1
    print(f"{checked} measurement(s): four colours, two themes, and nobody "
          f"confuses them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
