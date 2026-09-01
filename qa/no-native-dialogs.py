"""Is anything still asking through the browser instead of the application?

`window.confirm`, `window.alert` and `window.prompt` are the operating system's
dialogs, not this product's. Four problems, in the order they matter at a
counter:

**They block.** In a Tauri window the whole application freezes until the box
is answered. No toast appears, no background refresh completes, and a till that
has stopped responding looks broken rather than busy — at exactly the moment a
customer is standing in front of it.

**They cannot say what is at stake.** A native dialog gets one string and two
buttons labelled OK and Cancel. "Write off 40 units of Amoxicillin" needs the
quantity, the batch and the consequence, and the confirming button should say
*write off*.

**`prompt` cannot require an answer.** It returns a string, and Cancel and an
empty box are indistinguishable. One of the four found here was collecting the
name of whoever received a **controlled substance**, a legal record, with
nothing to stop it being blank.

**They look like Windows.** On a machine a pharmacy bought to run one
application, that is jarring in a way that reads as unfinished.

The replacements are `useConfirm` and `useAsk` in `components/Confirm`, and
`useToast`: or the imperative `toast` for modules that are not components.

    python qa/no-native-dialogs.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"

#: What to look for, and what to use instead.
BANNED = [
    (re.compile(r'\bwindow\.confirm\s*\('), "window.confirm",
     "useConfirm() from components/Confirm — it can name the action and "
     "park focus on Cancel"),
    (re.compile(r'\bwindow\.prompt\s*\('), "window.prompt",
     "useAsk() from components/Confirm — it can label the field and require "
     "an answer"),
    (re.compile(r'\bwindow\.alert\s*\('), "window.alert",
     "useToast() — a toast does not freeze the till"),
    # A bare `alert(...)`, but not `.alert(` on some object of our own.
    (re.compile(r'(?<![.\w])alert\s*\('), "alert",
     "useToast(), or the imperative `toast` where there is no component"),
    (re.compile(r'(?<![.\w])confirm\s*\((?!\s*\{)'), "confirm",
     "useConfirm() — a bare confirm() is the global one"),
]

#: Where the words appear legitimately: the component that replaced them
#: explains what it replaced, and this file names them to ban them.
EXEMPT = {"components/Confirm.tsx", "components/Toast.tsx"}


def main() -> int:
    found: list[str] = []
    scanned = 0

    for path in sorted(SRC.rglob("*.ts*")):
        rel = path.relative_to(SRC).as_posix()
        if rel in EXEMPT:
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            # Comments and doc lines talk about these on purpose.
            if stripped.startswith(("//", "*", "/*")):
                continue
            for pattern, name, instead in BANNED:
                if not pattern.search(line):
                    continue
                # `const confirm = useConfirm()` and `await confirm({...})`
                # are the replacement, not the thing being banned.
                if name == "confirm" and re.search(
                        r'useConfirm|confirmLabel|async function confirm', line):
                    continue
                found.append(
                    f"frontend/src/{rel}:{i}\n"
                    f"       {stripped[:96]}\n"
                    f"       {name} freezes the application. Use {instead}.")

    for report in found:
        print(f"  FAIL {report}\n")

    print(f"  {scanned} files read, {len(found)} native dialog(s)")
    if found:
        print("\na browser dialog blocks the whole till until somebody clicks "
              "OK, and cannot say what is about to happen")
        return 1
    print("\nevery question is asked in the application, not by the browser")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
