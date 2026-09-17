"""Open every screen in the pharmacy, at every branch, as the people who work there.

    python rehearse_operations.py --pharmacy 5

`rehearse_counter.py` works one script from search to payment. This does the
other half: it asks every screen in the application to load, at each branch, for
each role that would open it, against the real data — because a screen that
throws a 500 on a pharmacy's own catalogue is invisible until somebody clicks it,
and the person who clicks it is the client, in front of a customer.

Only reads. Nothing here writes anything, and it still runs inside a transaction
that is rolled back, so a screen that decides to record something on the way past
cannot leave it behind.

A 403 is not a failure. It is the permission system doing its job, and it is
reported separately so that the difference between "this cashier may not see the
ledger" and "the ledger is broken" stays visible.
"""
from __future__ import annotations

import argparse
import logging
import os
import pathlib
import re
import sys
from collections import defaultdict


def _target() -> str:
    env = pathlib.Path(__file__).with_name(".env")
    if not env.exists():
        sys.exit("backend/.env not found; nothing to read the target from.")
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SEED_TARGET_URL="):
            url = line.split("=", 1)[1].strip()
            if url:
                return url
    sys.exit("SEED_TARGET_URL is not set in backend/.env.")


parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("--pharmacy", type=int, default=5)
parser.add_argument("--branch", type=int, default=None)
parser.add_argument("--slow", type=float, default=2.5,
                    help="seconds after which a screen is called slow")
parser.add_argument("--roles", default="",
                    help="only these roles, comma separated (default: every "
                         "role that works at the branch)")
args = parser.parse_args()

os.environ["DATABASE_URL"] = _target()
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
logging.getLogger("httpx").setLevel(logging.WARNING)

from fastapi.testclient import TestClient                        # noqa: E402
from sqlalchemy.orm import sessionmaker                          # noqa: E402

from app import branch_scope, models as m, tenancy               # noqa: E402
from app.auth import create_token                                # noqa: E402
from app.database import engine, get_db                          # noqa: E402
from app.main import app                                         # noqa: E402

connection = engine.connect()
outer = connection.begin()
Rehearsal = sessionmaker(bind=connection, autocommit=False, autoflush=False,
                         join_transaction_mode="create_savepoint")
tenancy.install(Rehearsal)
branch_scope.install(Rehearsal)


def _rehearsal_db():
    db = Rehearsal()
    tenancy.stamp(db)
    branch_scope.stamp(db)
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _rehearsal_db
http = TestClient(app, raise_server_exceptions=False)


def screens() -> list[str]:
    """Every screen the application serves that needs nothing but a sign-in.

    Read off the routers themselves rather than listed by hand, so a router
    added next month is rehearsed without anybody remembering to add it. Paths
    that need an id are left out: they are covered by the counter rehearsal,
    which has real ids to put in them.
    """
    found: list[str] = []
    for path in sorted(pathlib.Path("app/routers").glob("*_router.py")):
        text = path.read_text(encoding="utf-8", errors="ignore")
        prefix = ""
        head = re.search(r'APIRouter\((?:[^)]*?)prefix="([^"]+)"', text)
        if head:
            prefix = head.group(1)
        for route in re.findall(r'@router\.get\("([^"]*)"', text):
            if "{" in route:
                continue
            whole = f"{prefix}{route}" or prefix
            if whole.startswith("/api"):
                found.append(whole)
    # Deduplicated, because two routers can serve the same prefix.
    return sorted(set(found))


#: Screens this deliberately does not open.
#:
#: Not because they are broken, but because opening them does something: a
#: backup runs, a PDF is rendered at length, a demo clock is read. A sweep meant
#: to be safe to run against a live pharmacy has to say which doors it leaves
#: shut rather than find out.
LEAVE_SHUT = {
    "/api/admin/backups", "/api/system/backups",
    "/api/dosage-abbreviations/sheet.pdf",
}

paths = [p for p in screens() if p not in LEAVE_SHUT]
print(f"target: {os.environ['DATABASE_URL'].split('@')[-1].split('/')[0]}")
print(f"{len(paths)} screen(s) to open\n")

broken: list[tuple[str, str, str, int, str]] = []
refused: dict[str, list[str]] = defaultdict(list)
slow: list[tuple[str, str, float]] = []

book = Rehearsal()
tenancy.stamp(book)
try:
    with tenancy.unscoped():
        pharmacy = book.get(m.Pharmacy, args.pharmacy)
        print(f"pharmacy: {pharmacy.name if pharmacy else args.pharmacy}")
        shops = (book.query(m.Branch).filter(m.Branch.pharmacy_id == args.pharmacy)
                 .order_by(m.Branch.id).all())
        if args.branch:
            shops = [b for b in shops if b.id == args.branch]

        for branch in shops:
            staff = (book.query(m.User)
                     .filter(m.User.pharmacy_id == args.pharmacy,
                             m.User.branch_id == branch.id, m.User.active.is_(True)).all())
            # One person per role that works here: the manager sees screens the
            # cashier may not, and a screen that only breaks for one of them is
            # the kind that reaches a client.
            by_role: dict[str, m.User] = {}
            wanted = {r.strip() for r in args.roles.split(",") if r.strip()}
            for person in staff:
                if wanted and person.role not in wanted:
                    continue
                by_role.setdefault(person.role, person)
            print(f"\n=== {branch.name} (branch {branch.id}) — "
                  f"{', '.join(sorted(by_role)) or 'nobody'} ===")
            if not by_role:
                continue

            for role, person in sorted(by_role.items()):
                http.headers["Authorization"] = "Bearer " + create_token(person, book)
                bad = allowed = denied = asked = 0
                print(f"  {role}:", flush=True)
                for path in paths:
                    import time
                    began = time.monotonic()
                    try:
                        said = http.get(path)
                        code = said.status_code
                        body = said.text[:150]
                    except Exception as exc:                     # noqa: BLE001
                        code, body = 599, f"{type(exc).__name__}: {exc}"[:150]
                    took = time.monotonic() - began
                    # Printed as it happens, not at the end. A sweep that says
                    # nothing for half an hour cannot be told apart from a sweep
                    # that has hung, and the screen it hung on is the answer.
                    if took > args.slow or code >= 500:
                        print(f"    {took:5.1f}s  {code}  {path}", flush=True)
                    if took > args.slow:
                        slow.append((branch.name, path, took))
                    if code in (401, 403):
                        denied += 1
                        refused[path].append(f"{branch.name}/{role}")
                    elif code in (400, 404, 422):
                        # The endpoint wants arguments this sweep does not know
                        # how to supply — a date range, a code to look up. It
                        # answering "you have not told me what to convert" is
                        # the screen working, not failing, and counting it as a
                        # fault buries the ones that are.
                        asked += 1
                    elif code >= 400:
                        bad += 1
                        broken.append((branch.name, role, path, code, body))
                    else:
                        allowed += 1
                print(f"    {allowed:>3} open, {denied:>3} not theirs to see, "
                      f"{asked:>2} want arguments"
                      + (f", {bad} BROKEN" if bad else ""), flush=True)
finally:
    http.headers.pop("Authorization", None)
    book.close()
    outer.rollback()
    connection.close()

print("\n" + ("=" * 66))
if slow:
    print(f"\nslow to open (over {args.slow:g}s):")
    for where, path, took in sorted(slow, key=lambda s: -s[2])[:12]:
        print(f"  {took:5.1f}s  {path}   at {where}")
if broken:
    print(f"\n{len(broken)} screen(s) would not open:\n")
    seen = set()
    for where, role, path, code, body in broken:
        if (path, code) in seen:
            continue
        seen.add((path, code))
        print(f"  {code}  {path}")
        print(f"        {where}, as {role}")
        print(f"        {body}")
else:
    print("\nevery screen opened, at every branch, for every role that works there")
print("nothing was written: the whole sweep was rolled back.")
sys.exit(1 if broken else 0)
