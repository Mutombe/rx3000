"""How long a screen takes to open, against the real database, and why.

    python time_remote.py /api/register /api/settlements

Times each screen as the browser would see it and counts the SQL statements it
took. Both numbers matter and neither replaces the other: a screen can be slow
because one query is slow, or because it ran nine hundred fast ones. The second
is the usual answer, is invisible on a laptop, and is what a hosted database
turns into a minute of somebody's afternoon.

Read-only, and rolled back regardless.
"""
from __future__ import annotations

import argparse
import logging
import os
import pathlib
import sys
import time


def _target() -> str:
    env = pathlib.Path(__file__).with_name(".env")
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SEED_TARGET_URL="):
            return line.split("=", 1)[1].strip()
    sys.exit("SEED_TARGET_URL is not set in backend/.env.")


parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
parser.add_argument("paths", nargs="+")
parser.add_argument("--pharmacy", type=int, default=5)
parser.add_argument("--branch", type=int, default=5)
args = parser.parse_args()

os.environ["DATABASE_URL"] = _target()
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
logging.getLogger("httpx").setLevel(logging.WARNING)

from fastapi.testclient import TestClient                        # noqa: E402
from sqlalchemy import event                                     # noqa: E402
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


def _db():
    db = Rehearsal()
    tenancy.stamp(db)
    branch_scope.stamp(db)
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _db
http = TestClient(app, raise_server_exceptions=False)

counted = {"n": 0}


@event.listens_for(engine, "before_cursor_execute")
def _count(conn, cursor, statement, parameters, context, executemany):
    counted["n"] += 1


book = Rehearsal()
tenancy.stamp(book)
try:
    with tenancy.unscoped():
        who = (book.query(m.User)
               .filter(m.User.pharmacy_id == args.pharmacy,
                       m.User.branch_id == args.branch,
                       m.User.active.is_(True))
               .order_by(m.User.role != "manager", m.User.id).first())
        if who is None:
            sys.exit(f"nobody active at branch {args.branch}")
        http.headers["Authorization"] = "Bearer " + create_token(who, book)
        print(f"as {who.username} ({who.role}) at branch {args.branch}\n")
        print(f"{'seconds':>8}  {'queries':>7}  {'status':>6}  screen")
        for path in args.paths:
            counted["n"] = 0
            began = time.monotonic()
            said = http.get(path)
            took = time.monotonic() - began
            print(f"{took:8.1f}  {counted['n']:7,}  {said.status_code:>6}  {path}")
finally:
    http.headers.pop("Authorization", None)
    book.close()
    outer.rollback()
    connection.close()
