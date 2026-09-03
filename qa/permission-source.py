"""Does any screen decide for itself what somebody may do?

There is one rule about who may do what, it lives in
`backend/app/services/permissions.py`, and it is not simple: role defaults,
grants by name, denials that beat grants, per-branch scope, per-transaction
ceilings, daily allowances, hours, days and expiry. The server resolves all of
that and sends a flat set of booleans on `/api/auth/me`, which `session.tsx`
hands to `can()`.

A second implementation of that rule in TypeScript would drift from the first
inside a month. What makes it worth a check rather than a note is how the drift
presents: not as a wrong answer somewhere in a report, but as a button that is
visible, enabled, and then refused — which teaches the person using it that the
software is unreliable rather than that they lack the authority. The workaround
they reach for is somebody else's password, and from then on the audit trail
says "manager" for everything.

So this looks for the shortcut, which is always the same one:

    if (user.role === "admin") { ... }

It is tempting precisely because it works, today, for the case in front of you.
It stops working the first time an assistant is granted a void by name — the
whole reason the grant table exists.

WHAT IS ALLOWED

Showing somebody their role: `<span>{user.role}</span>`, a column in the staff
list, a role picker. Displaying a role is not deciding with it.

`session.tsx` itself, which is where the answers arrive.

    python qa/permission-source.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"

#: Comparing a role against a literal, which is a decision rather than a
#: display. Covers ===, !==, == and !=, and the `includes` form that a list of
#: roles takes.
COMPARISON = re.compile(
    r'\brole\b\s*[!=]==?\s*["\']|'
    r'["\'](?:admin|manager|pharmacist|assistant|cashier)["\']\s*[!=]==?\s*\S*\brole\b|'
    r'\[[^\]]*["\'](?:admin|manager)["\'][^\]]*\]\s*\.\s*includes\s*\(\s*\w*\.?role')

#: Where the answers legitimately live.
EXEMPT = {
    "session.tsx": "the provider that receives the resolved matrix",
}


def strip_comments(text: str) -> str:
    """Comments discuss the rule; they do not implement it.

    Learnt from `button-contrast.py`, which never stripped CSS comments and so
    hid a real fault behind a note somebody had written above it.
    """
    text = re.sub(r'/\*.*?\*/', "", text, flags=re.S)
    return re.sub(r'^\s*//.*$', "", text, flags=re.M)


def main() -> int:
    findings: list[str] = []
    read = 0

    for file in sorted(SRC.rglob("*.ts*")):
        if file.name in EXEMPT:
            continue
        read += 1
        text = strip_comments(file.read_text(encoding="utf-8", errors="replace"))
        for hit in COMPARISON.finditer(text):
            line = text.count("\n", 0, hit.start()) + 1
            findings.append(
                f"frontend/src/{file.relative_to(SRC).as_posix()}:{line}\n"
                f"       {hit.group(0).strip()}\n"
                f"       decides a permission from a role. Ask the server: "
                f"useCan(\"the.capability\").")

    for finding in findings:
        print(f"  X    {finding}\n")

    print(f"  {read} file(s) read; {len(findings)} decide a permission from a "
          f"role")
    for name, why in sorted(EXEMPT.items()):
        print(f"       {name} is exempt: {why}")

    if findings:
        print("\nthe rule has ceilings, hours, branch scope and denials that "
              "beat grants. A role comparison cannot see any of them, and the "
              "way it fails is a button that works until somebody is granted "
              "something by name.")
        return 1
    print("\nevery screen asks the server what somebody may do, so there is "
          "one rule and not two")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
