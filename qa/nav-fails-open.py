"""Does the sidebar survive not knowing yet?

This is a regression test for a bug that was reported as "I logged in as admin
and I no longer see the branch management and other high level operations".

Nothing was wrong with the permissions. The server had it right — all
seventeen capabilities true, group-wide sight true. The sidebar filtered on
`can()`, and `can()` is false before the answer arrives. So for as long as
`/api/auth/me` took, an administrator's Control Panel, Analytics and Stock
performance were simply not in the list; on a cold server that is tens of
seconds, if the read failed it was until they reloaded, and for the length of a
deploy where the app is new and the api is not it was permanent.

WHY THE TWO DIRECTIONS ARE NOT SYMMETRICAL

Showing a link somebody may not use costs one click and a clear sentence,
because every one of those screens refuses on its own — the server is the rule
and the sidebar is a courtesy. Hiding a link somebody is entitled to costs
their belief that the product works, and it is not even recoverable by trying:
there is nothing to click.

So filtering happens only on a definite answer. Not fetched, failed, or a
response with no `can` field are all "do not know", and all three show
everything.

WHAT THIS CHECKS

Statically, in the source, because the alternative is a browser and this is a
rule about one expression:

  1. `session` exposes `known`, and it is false unless a `can` map arrived.
  2. The nav filter returns the unfiltered list when `known` is false.
  3. No component refuses to render on `can()` alone — the same fault, one
     level down, which took the Authority tab blank on a slow load.

    python qa/nav-fails-open.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"
SESSION = SRC / "session.tsx"
LAYOUT = SRC / "components" / "Layout.tsx"

failures: list[str] = []


def check(ok: bool, said: str, why: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {said}")
    if not ok:
        failures.append(why or said)


def main() -> int:
    session = SESSION.read_text(encoding="utf-8")
    layout = LAYOUT.read_text(encoding="utf-8")

    check("known" in session,
          "the session says whether it knows yet",
          "session.tsx has no `known`, so nothing can tell 'still loading' "
          "from 'may do nothing'")

    # `known` must be derived from the arrival of the map, not from `loading`
    # alone: an older server responds quickly and carries no `can` at all.
    derived = re.search(r'const known = ([^;]+);', session)
    check(derived is not None and "me.can" in derived.group(1),
          "and it decides that from the `can` map having arrived",
          "known is not derived from the presence of me.can, so a response "
          "from an older server reads as a person with no authority — which "
          "is exactly the deploy window where the app is new and the api "
          "is not")

    # The filter must bail out before filtering.
    nav = re.search(r'const visibleNav = React\.useMemo\(\(\) => \{(.*?)\n  \}, ',
                    layout, re.S)
    check(nav is not None, "the nav builds its list in one place",
          "could not find visibleNav, so this check cannot speak to it")
    if nav:
        body = nav.group(1)
        early = re.search(r'if \(!session\.known\)\s*return NAV;', body)
        check(early is not None,
              "and returns the whole list while the answer is unknown",
              "visibleNav filters before knowing. That is the reported bug: "
              "an administrator's Control Panel is missing for as long as the "
              "session takes to load, and for good if it fails")
        if early:
            check(body.index(early.group(0)) < body.find(".filter("),
                  "before it filters anything, not after",
                  "the bail-out is below the filter, so it does not prevent "
                  "it")

    # The same fault one level down: a panel that renders nothing on can()
    # alone disappears on a slow load rather than on a refusal.
    for file in sorted(SRC.rglob("*.tsx")):
        text = file.read_text(encoding="utf-8", errors="replace")
        text = re.sub(r'/\*.*?\*/', "", text, flags=re.S)
        text = re.sub(r'^\s*//.*$', "", text, flags=re.M)
        for hit in re.finditer(r'if \(!\s*(may|can)\b[^)]*\)\s*return null;', text):
            # Allowed when it is guarded by `known`.
            window = text[max(0, hit.start() - 200):hit.end()]
            if "session.known" in window:
                continue
            line = text.count("\n", 0, hit.start()) + 1
            check(False,
                  f"{file.relative_to(SRC).as_posix()}:{line} renders nothing "
                  f"on a capability alone",
                  f"{file.relative_to(SRC).as_posix()}:{line}: "
                  f"`{hit.group(0)}` is false while the session loads, so the "
                  f"panel is absent rather than pending. Guard it with "
                  f"session.known so it only refuses on a definite no")

    print()
    if failures:
        for f in failures:
            print(f"  {f}\n")
        return 1
    print("the sidebar shows everything until the server has actually said, so "
          "a slow read looks slow rather than looking like a smaller product")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
