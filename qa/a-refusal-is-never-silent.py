"""When the server refuses, does anybody tell the person standing there?

WHAT WENT WRONG

A pharmacist opened the recall screen and the console said:

    GET /api/auth/users -> 403 | server said: Requires role: admin

Six screens wanted a list of staff to fill an "assign to" box. All six called
`/users`, which is administration and needs an administrator, so for every
pharmacist and cashier the request was refused and the dropdown was simply
empty. Every one of them ended `.catch(() => {})`, so nothing was said. The
software worked out exactly what was wrong, wrote it down in a place only a
developer looks, and showed the user an empty box.

That pattern is the subject of this guard. A refused request that nobody
mentions is worse than a crash: a crash gets reported the same afternoon, and
an empty dropdown gets worked around for a year.

WHAT IS CHECKED

Every `.catch(() => {})` in the frontend has to be deliberate. Silence is
sometimes right — the offline queue reading its own local state while the
network is known to be down, a best-effort refresh of something already on
screen — so the rule is not "never swallow", it is "say why". A swallow
carrying a comment that begins "Deliberately silent" is a decision somebody
made; one without is an oversight.

It also checks that nothing has gone back to calling the admin endpoint for
what is really a roster question.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

passed = 0
failed = 0


def check(condition: bool, message: str, extra: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  ok   {message}")
    else:
        failed += 1
        print(f"  FAIL {message}{('   ' + extra) if extra else ''}")


files = sorted(p for p in SRC.rglob("*.ts*") if "node_modules" not in str(p))
check(len(files) > 50, f"{len(files)} source files to read")

# ------------------------------------------------- every swallow is on purpose

print("\n  every swallowed refusal is a decision somebody made\n")

SWALLOW = re.compile(r"\.catch\(\s*\(\s*\)\s*=>\s*\{\s*\}\s*\)")

undocumented: list[tuple[str, int, str]] = []
deliberate = 0
for path in files:
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if not SWALLOW.search(line):
            continue
        # The reason may sit on the swallow's own line or in the comment block
        # immediately above it.
        window = "\n".join(lines[max(0, i - 6):i + 1])
        if "Deliberately silent" in window:
            deliberate += 1
        else:
            undocumented.append((str(path.relative_to(SRC)), i + 1, line.strip()[:60]))

check(not undocumented,
      f"{deliberate} swallow(s), each saying why it is silent",
      "" if not undocumented else
      "; ".join(f"{f}:{n}" for f, n, _ in undocumented[:6]))

# ----------------------------------------- the roster is not an admin question

print("\n  a colleague list does not need an administrator\n")

callers = []
for path in files:
    text = path.read_text(encoding="utf-8")
    # `/api/auth/users` is legitimate on the administration screens, which do
    # manage accounts. It is not legitimate as a way to fill an assignment box.
    if '"/api/auth/users"' in text and path.name not in ("Admin.tsx", "HqPermissions.tsx"):
        callers.append(str(path.relative_to(SRC)))

check(not callers,
      "no ordinary screen fills a dropdown from the admin user list",
      "" if not callers else
      f"{', '.join(callers)} would be refused for everybody but an admin")

roster = (ROOT / "backend" / "app" / "routers" / "auth_router.py").read_text(encoding="utf-8")
check('@router.get("/roster"' in roster,
      "there is a roster endpoint for them to use instead")
check(re.search(r'@router\.get\("/roster".*?\n.*?get_current_user', roster, re.S) is not None,
      "and it asks only that you are signed in",
      "a roster behind require_role is the bug all over again")
check(re.search(r'@router\.get\("/roster".*?User\.active', roster, re.S) is not None,
      "and leaves out people who no longer work here",
      "assigning work to somebody who left is how it goes missing")

print(f"\n{passed} passed, {failed} failed")
if failed:
    print("\nthe server said what was wrong. Somebody has to pass it on.")
sys.exit(1 if failed else 0)
