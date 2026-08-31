"""Is anything linking straight at the API with a plain anchor?

Every request this product makes carries the session in an `Authorization`
header. An `<a href="/api/...">` cannot carry a header — the browser navigates,
sends no token, and the server refuses. The link looks perfectly ordinary in
the source and is dead in the hand.

WHERE THIS BIT

The licence register. Each row offered the certificate as
`<a href="/api/compliance/documents/{id}/file">`, so every attempt to open a
licence was refused — on the one screen whose entire purpose is producing the
document when an inspector asks for it. Nothing in the code looked wrong, and
nothing failed loudly: a 401 opened in a new tab, behind the tab somebody was
already looking at.

THE FIX IS NOT A TOKEN IN THE QUERY STRING

That is the usual workaround and it is worse than the bug. A URL travels
through every access log, proxy log and browser history between here and the
server, and the value being written into them is the key to the whole
pharmacy. `api.blob` exists for this: an ordinary authenticated fetch that
happens to return bytes, from which an object URL is opened.

    python qa/authed-links.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"

#: Paths that really are public — served without a session, by design.
#: The patient portal is reached from a signed link by somebody who has no
#: account at all, so its endpoints must work without a header.
PUBLIC = ("/api/portal/", "/api/public/", "/api/health")


def main() -> int:
    findings: list[str] = []
    anchors = 0

    for file in sorted(SRC.rglob("*.tsx")):
        text = file.read_text(encoding="utf-8", errors="replace")
        # `href` on an anchor pointing at the API, whether a literal or a
        # template. Both forms shipped.
        for match in re.finditer(
                r'<a\b[^>]{0,400}?href=\{?[`"\']([^`"\']*?/api/[^`"\']*)', text,
                re.S):
            anchors += 1
            path = match.group(1)
            if any(p in path for p in PUBLIC):
                continue
            line = text.count("\n", 0, match.start()) + 1
            findings.append(
                f"frontend/src/{file.relative_to(SRC).as_posix()}:{line}\n"
                f"       href=\"{path[:64]}\"\n"
                f"       an anchor cannot carry the Authorization header, so "
                f"this navigates\n"
                f"       without a session and the server refuses. Use "
                f"`api.blob(path)` and\n"
                f"       open the object URL — never a token in the query "
                f"string.")

    # The same fault through `window.open` and `window.location`, which is how
    # somebody fixes the anchor without fixing the problem.
    for file in sorted(SRC.rglob("*.ts*")):
        text = file.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(
                r'window\.(?:open|location(?:\.href)?\s*=)\s*\(?\s*[`"\']'
                r'([^`"\']*?/api/[^`"\']*)', text, re.S):
            path = match.group(1)
            if any(p in path for p in PUBLIC):
                continue
            line = text.count("\n", 0, match.start()) + 1
            findings.append(
                f"frontend/src/{file.relative_to(SRC).as_posix()}:{line}\n"
                f"       window.open(\"{path[:56]}\")\n"
                f"       navigating to the API sends no session either. Same "
                f"fix.")

    for finding in findings:
        print(f"  X    {finding}\n")

    print(f"  {anchors} anchor(s) point at the API; {len(findings)} of them "
          f"cannot carry a session")
    if findings:
        print("\na link the browser follows is a request without a token. "
              "api.blob attaches one.")
        return 1
    print("\nevery authenticated file is fetched with its session, not linked at")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
