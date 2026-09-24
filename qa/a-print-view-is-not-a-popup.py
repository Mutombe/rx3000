"""Nothing prints through a window the till is not allowed to open.

WHAT HAPPENED.

Four separate places built a document and printed it by opening a window and
writing into it. In a browser that is the right shape: the reader scrolls it,
decides whether to print, and can save it as a PDF from the same dialog.

The desktop application is a WebView, and a WebView refuses window.open. There
is no pop-up blocker on a till to find and no site to allow. So in the
installed application:

  * the label and receipt path said "The print window was blocked. Allow
    pop-ups for this site and print again", to somebody standing at a counter
    where no such setting exists,
  * `printDocument` — every claim copy, waybill and statement — did
    `if (!w) return`, and printed nothing at all with no message,
  * and because the label path falls back to this one, a printer fault at the
    dispensary ended in a message about a browser setting.

WHAT THIS CHECKS.

`window.open("")` with an empty address means "give me a window to write a
document into", which is the printing shape. It has to go through
`printView.ts`, which takes a window where one is allowed and a hidden iframe
where it is not.

`window.open(url)` with a real address is left alone. That is navigation, not
printing, and it is a different question with a different answer.

Run by exit code. Nought is a pass.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"
HOME = "printView.ts"

#: window.open with an empty first argument: a window to write into.
BLANK = re.compile(r"""window\.open\(\s*(["'`])\s*\1""")


def main() -> int:
    faults = []
    for path in sorted(SRC.rglob("*.ts")) + sorted(SRC.rglob("*.tsx")):
        if path.name == HOME:
            continue
        text = path.read_text(encoding="utf-8")
        for match in BLANK.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            faults.append(f"{path.relative_to(ROOT).as_posix()}:{line}")

    if not faults:
        print("Every printed document goes through printView, so it prints on "
              "a till as well as in a browser.")
        return 0

    print("\nSomething prints by opening a window.\n")
    for fault in faults:
        print(f"    {fault}")
    print("\n  The desktop shell refuses windows, so on a till this either asks "
          "for a\n  pop-up setting that does not exist or silently prints "
          "nothing.")
    print("  Use printView or claimPrintView from printView.ts: a window where "
          "one is\n  allowed, a hidden frame where it is not, the same document "
          "either way.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
