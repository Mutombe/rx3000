"""Every screen sends a label the same way, or the toast is a lie.

WHAT HAPPENED.

The dispensary printed labels through `printLabelsDirect`, which asks how this
till is set up and sends the right thing. The reprint dialog printed them
through `printLines`, which is ESC/POS bytes, always, whatever the till is set
to.

On a Zebra those bytes are a job the printer accepts and throws away. So the
reprint said "1 label(s) printed" and the roll never moved — and a reprint
screen is the worst possible place for that, because the person using it is
already there reprinting something that did not come out the first time.

Nothing was broken in either function. The fault was that there were two
routes, and only one of them had been taught about the printer.

WHAT THIS CHECKS.

`printLines` sends bytes for a KIND of document. A label has a route that
decides between ZPL, a PDF through the driver, and ESC/POS, and that decision
lives in `printLabelsDirect`. So nothing outside `shellPrinter.ts` may call
`printLines` to print a label: a screen either calls `printLabelsDirect` or it
is not printing a label.

`printLines` for a receipt or a price ticket is left alone. Those are ESC/POS
by definition, on a receipt head, where there is no ambiguity about the
language and nothing to decide.

Run by exit code. Nought is a pass.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"
#: Where the decision is allowed to live.
HOME = "shellPrinter.ts"

#: A call to printLines whose document kind is the dispensing label. The kind
#: is the third argument and defaults to "label", so a two-argument call is a
#: label call just as much as one that says so.
CALL = re.compile(r"printLines\s*\(([^;]*?)\)\s*[;,)]", re.S)


def arguments(args: str) -> list:
    """The top level arguments of a call, so a nested comma is not an argument."""
    out, depth, quote, current = [], 0, "", ""
    for char in args:
        if quote:
            current += char
            if char == quote:
                quote = ""
            continue
        if char in "\"'`":
            quote = char
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        if char == "," and depth == 0:
            out.append(current.strip())
            current = ""
            continue
        current += char
    if current.strip():
        out.append(current.strip())
    return out


def kind_of(args: str) -> str:
    """The document kind a printLines call names.

    The kind is the third argument and defaults to the dispensing label, so a
    call that does not pass one is a label call.

    A third argument that is not a literal is a ROUTED call — `printRoll` in
    the dispensary takes `"price" | "delivery"` and hands it straight through.
    Those are reported as routed rather than guessed at: reading them as labels
    made this check fail on code that was right, and a check that cries wolf
    about correct code is one somebody turns off.
    """
    parts = arguments(args)
    if len(parts) < 3:
        return "label"
    said = re.fullmatch(r'"(\w+)"', parts[2])
    return said.group(1) if said else "routed"


def main() -> int:
    faults = []
    for path in sorted(SRC.rglob("*.ts")) + sorted(SRC.rglob("*.tsx")):
        if path.name == HOME:
            continue
        text = path.read_text(encoding="utf-8")
        for match in CALL.finditer(text):
            if kind_of(match.group(1)) != "label":
                continue
            line = text.count("\n", 0, match.start()) + 1
            faults.append(f"{path.relative_to(ROOT).as_posix()}:{line}")

    if not faults:
        print("Every screen sends a label by the one route that knows what the "
              "printer is.")
        return 0

    print("\nA screen is printing labels its own way.\n")
    for fault in faults:
        print(f"    {fault}")
    print(f"\n  printLines sends ESC/POS whatever the till is set to, so on a "
          f"Zebra\n  this prints nothing and says it printed.")
    print(f"  Call printLabelsDirect instead; it decides between ZPL, the "
          f"driver and\n  ESC/POS from what Windows says the printer is.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
