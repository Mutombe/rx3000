"""Which endpoints need no credential, and did somebody decide that?

An endpoint is public in this application by OMISSION. There is no marker for
it: a handler that simply does not ask for `get_current_user` is open, and it
looks exactly like one that does until you read its signature. Nothing said so
out loud, nothing listed them, and two had been open for a long time without
anybody meaning it.

WHY IT WAS HARD TO SEE

Because they appeared to work correctly. With nobody signed in there is no
pharmacy in force, and tenancy narrows every query to rows with no pharmacy —
of which there are none. So an unauthenticated request for somebody's cash-up
answered "that shift no longer exists" and read exactly like a closed door.

It was the right answer arrived at by accident, and it would have stopped
being the right answer the moment one row carried a null tenant. Protection
that comes from a filter having nothing to match is not protection; it is a
coincidence that has not been tested.

WHAT THIS CHECKS

That the set of endpoints needing no credential is exactly the set written
down below, each with the reason it is public. A new one shows up here as a
failure, which is the point: making an endpoint public should cost somebody a
sentence explaining why.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from app.main import app                           # noqa: E402

#: Endpoints that genuinely need no credential, and why each one does not.
#:
#: The reason matters more than the entry. "Nobody is signed in yet" is the
#: only shape of answer that belongs here: a sign-in, a public form, or a
#: token that IS the credential and is checked inside the handler.
ALLOWED: dict[tuple[str, str], str] = {
    ("GET", "/api/health"):
        "a load balancer asking whether this process is alive",
    ("GET", "/api/jurisdiction"):
        "which country's rules this install runs, needed by the sign-in "
        "screen before anybody has signed in",
    ("POST", "/auth/token"):
        "signing in. There is no credential before this one",
    ("POST", "/api/auth/login"):
        "the same, by the name the application itself uses",
    ("POST", "/api/auth/demo"):
        "a visitor asking for a demonstration. They have no account yet, "
        "which is the entire point of it",
    ("GET", "/api/auth/demo/length"):
        "how long a demo lasts, quoted on the sign-in screen",
    ("POST", "/api/auth/reset-with-pin"):
        "recovering a forgotten password with the till PIN. Somebody locked "
        "out cannot sign in to ask",
    ("GET", "/api/portal/patient/{token}"):
        "a patient link. The signed token IS the credential and names one "
        "patient inside its own signature",
    ("POST", "/api/portal/patient/{token}/confirm"):
        "the same link, answering the question it was sent to ask",
    ("GET", "/api/portal/doctor/{token}"):
        "a prescriber link, on the same terms",
    ("POST", "/api/portal/doctor/login"):
        "a prescriber signing in to their own portal",
    ("POST", "/api/portal/doctor/prescriptions"):
        "a prescriber writing a script, behind the portal's own session",
    ("POST", "/api/public/web-to-lead"):
        "the marketing site's form. It is a stranger by definition",
    ("POST", "/api/public/web-to-case"):
        "the same, for support",
    ("POST", "/api/scanner/claim"):
        "a phone taking a pairing. The code shown on the counter's screen is "
        "the credential: single use, three minutes, and worth nothing after",
    ("POST", "/api/scanner/scan"):
        "a paired phone sending a string. Its token is checked in the handler "
        "and can do nothing else",
    ("GET", "/api/scanner/paired"):
        "the same token, asking what it is attached to",
    ("GET", "/api/prescriptions/holds/reasons"):
        "the fixed list of reasons a script can be held. Reference data with "
        "no pharmacy in it",
}

#: Names that mean a credential was demanded. `requires` and `require_role`
#: both resolve a user before they decide anything.
GATES = {"get_current_user", "require_role", "requires", "checker"}

passed = 0
failed = 0


def check(condition: bool, message: str) -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  ok   {message}")
    else:
        failed += 1
        print(f"  FAIL {message}")


spec = app.openapi()
public: set[tuple[str, str]] = set()
total = 0
for path, operations in spec["paths"].items():
    for method, operation in operations.items():
        if method.upper() not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            continue
        total += 1
        # FastAPI writes a security block onto an operation whose dependency
        # tree resolves a credential. No block means nothing asked for one.
        if "security" not in operation:
            public.add((method.upper(), path))

print(f"\n  {len(public)} of {total} endpoints need no credential\n")

unexplained = sorted(public - set(ALLOWED))
for method, path in unexplained:
    print(f"  FAIL {method} {path} is open and nothing says why")
    failed += 1
if not unexplained:
    passed += 1
    print("  ok   every open endpoint is one somebody decided on")

# The other direction. An entry that is no longer open is an entry that has
# been fixed, and leaving it here would quietly bless the next one to appear
# under that path.
stale = sorted(set(ALLOWED) - public)
for method, path in stale:
    print(f"  FAIL {method} {path} is listed as open but is not. Remove it.")
    failed += 1
if not stale:
    passed += 1
    print("  ok   and nothing is listed that has since been closed")

# The two that were open by omission, named so they cannot quietly come back.
for method, path in (("GET", "/api/shifts/{shift_id}/cashup"),
                     ("DELETE", "/api/prescriptions/{rx_id}/draft")):
    check((method, path) not in public,
          f"{method} {path} demands a credential")

print(f"\n{passed} passed, {failed} failed")
if failed:
    print("\nan endpoint is public here by omission, which is why it has to be "
          "written down: a handler that forgot to ask looks exactly like one "
          "that never needed to.")
sys.exit(1 if failed else 0)
