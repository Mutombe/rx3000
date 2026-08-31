"""Does a component sheet style an element the global sheet also paints?

Three times now, the same shape.

  `.term-option` set an ink colour and no background, so it inherited the
  primary accent fill from `button, .btn` — every allergy in the picker was
  near-black text on a near-black block, at 1.07:1.

  The patient portal set a colour on `.pp` and let its children inherit it.
  They did not: the portal is a route inside the staff application, so the
  staff stylesheet is loaded too, and `h1 { color: var(--ink) }` beats an
  inherited value every time. `.pp h1` sized the heading and never coloured it,
  so the patient's own name rendered near-black on the portal's near-black
  card — invisible, on their own page.

The rule underneath both: **an element selector always beats inheritance.** A
component that must look a certain way has to declare that way. Hoping to
inherit works right up until somebody adds a global rule for that element,
which is a thing stylesheets do.

WHY THIS READS CSS AND NOT THE COMPONENTS

Four attempts went at the JSX first, and all four were wrong in ways worth
recording, because each looked like it worked.

  It counted the global rule as its own coverage — `h1 { color }` read as proof
  an `h1` gets painted. It reported all-clear on the tree where the patient's
  name was invisible, which is the worst thing a check can say.

  It keyed descendant rules by their last word, so `.stat .label { color }`
  covered every `<label>` in the product, and a bare `<h1>` was skipped for
  having no class — although a bare element is precisely what breaks, having
  nothing of its own to win the cascade with.

  Then it reported 1,128 places, because taking the global ink is not a bug on
  the default surface; it is the design.

  Then it narrowed to "inside a container that sets its own colour" and
  reported an `<input>` as being inside `.btn` — because a regex cannot see
  which elements are nested in which. That is not a bug in the pattern; it is
  the ceiling of reading JSX with a regex.

The collision is visible in the stylesheets alone, and needs no DOM. A
component sheet says `.pp { color: … }` and then writes `.pp h1 { font-size }`
— it has that element in hand and does not colour it — while the global sheet
carries a bare `h1 { color }`. Both facts are in CSS. That is what is read here.

    python qa/inherited-colour.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"

#: The sheet whose bare element rules win against anything merely inherited.
GLOBAL = SRC / "styles.css"

#: Sheets for components rendered while the global sheet is also loaded.
COMPONENT_SHEETS = [SRC / "portal" / "portal.css"]

#: Elements a global sheet is likely to paint by name.
ELEMENTS = {"h1", "h2", "h3", "h4", "h5", "label", "button", "input",
            "select", "textarea", "a", "p", "li", "td", "th"}


def rules(sheet: Path) -> list[tuple[str, str]]:
    """(selector, body) for every rule, comments and at-rule headers removed."""
    if not sheet.exists():
        return []
    css = re.sub(r'/\*.*?\*/', ' ',
                 sheet.read_text(encoding="utf-8", errors="replace"), flags=re.S)
    out = []
    for selector, body in re.findall(r'([^{}]+)\{([^{}]*)\}', css):
        for part in selector.split(","):
            part = part.strip()
            if part and not part.startswith("@"):
                out.append((part, body))
    return out


def sets(body: str, prop: str) -> bool:
    if prop == "background":
        return bool(re.search(r'(?:^|[;\s])background(?:-color)?\s*:', body))
    return bool(re.search(rf'(?:^|[;\s]){prop}\s*:', body))


def tail(selector: str) -> str:
    """The element or class this selector actually paints."""
    words = selector.replace(">", " ").replace("+", " ").replace("~", " ").split()
    return re.sub(r'(:{1,2}[a-z-]+(\([^)]*\))?)+$', '', words[-1]) if words else ""


def main() -> int:
    # What the global sheet paints by bare element name. These are the rules a
    # component cannot out-inherit; it can only out-declare them.
    hazards: dict[str, set[str]] = {}
    for selector, body in rules(GLOBAL):
        if selector in ELEMENTS:
            for prop in ("color", "background"):
                if sets(body, prop):
                    hazards.setdefault(selector, set()).add(prop)

    if not hazards:
        print("  no bare element rules in the global sheet; nothing to collide")
        return 0

    print(f"  {GLOBAL.name} paints these elements by name, beating inheritance:")
    for element, props in sorted(hazards.items()):
        print(f"    {element:<8} {', '.join(sorted(props))}")
    print()

    findings: list[str] = []
    for sheet in COMPONENT_SHEETS:
        name = sheet.relative_to(SRC).as_posix()
        component = rules(sheet)

        # The roots that set a colour for their contents to inherit, e.g. `.pp`.
        roots = sorted({selector.lstrip(".") for selector, body in component
                        if re.fullmatch(r'\.[A-Za-z][\w-]*', selector)
                        and sets(body, "color")})
        if not roots:
            continue

        # Every element this sheet has in hand, and what it declares on it.
        for selector, body in component:
            element = tail(selector)
            if element not in hazards:
                continue
            missing = {p for p in hazards[element] if not sets(body, p)}
            if not missing:
                continue
            findings.append(
                f"{name}   {selector} {{ … }}\n"
                f"       styles a <{element}> and sets no "
                f"{' or '.join(sorted(missing))} of its own, while "
                f"styles.css has {element} {{ {', '.join(sorted(hazards[element]))} }}.\n"
                f"       .{roots[0]}'s colour is inherited; that bare rule is "
                f"not — it wins.")

    for finding in findings:
        print(f"  X    {finding}\n")

    checked = sum(len(rules(s)) for s in COMPONENT_SHEETS)
    print(f"  {checked} component rule(s) read against "
          f"{len(hazards)} global element rule(s); {len(findings)} collide")
    if findings:
        print("\nan element selector always beats an inherited value. A "
              "component that must look a certain way has to declare it.")
        return 1
    print("\nevery element these sheets style declares what the global sheet "
          "would otherwise impose on it")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
