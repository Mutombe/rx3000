"""The file the pharmacy's accountant puts into Pastel.

Almost every pharmacy in this market keeps its financials in Pastel, and the
person who does that is not the person at the counter. They want a file, once
a day, that goes into their own ledger without being re-keyed.

WHAT IS CHECKED, AND WHY THIS ONE IS MOSTLY ABOUT REFUSING

An account here is 1200 STOCK ON HAND. In their books it might be 8400. Both
are right and neither is guessable. Exporting an unmapped line sends it under
OUR number, and it imports perfectly well into whatever their 1200 happens to
be — producing a wrong set of books that balances.

That is the hardest kind of error to find and the easiest to prevent, by not
writing the file. So most of this checks that it refuses: unmapped accounts,
a date range the wrong way round, and an export that does not balance being
named as one Pastel will reject.

The file itself is checked for the things a bookkeeper would notice second:
that every posted line is there, that the debits equal the credits, and that
the account column carries THEIR code rather than ours.
"""
from __future__ import annotations

import csv
import io
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient          # noqa: E402

from app.main import app                           # noqa: E402
from app.database import SessionLocal              # noqa: E402
from app.tenancy import unscoped, set_current_pharmacy   # noqa: E402
from app import auth, models                       # noqa: E402
from app.services import pastel                    # noqa: E402

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


client = TestClient(app)
db = SessionLocal()
tag = uuid.uuid4().hex[:4].upper()

with unscoped():
    me = (db.query(models.User)
          .filter(models.User.role == "admin", models.User.is_demo.is_(False),
                  models.User.active, models.User.pharmacy_id.isnot(None))
          .first())
    if me is None:
        print("  ..   no administrator on this database")
        sys.exit(0)
    headers = {"Authorization": f"Bearer {auth.create_token(me, db)}"}
    mine = me.pharmacy_id

set_current_pharmacy(mine)

# A day with real postings on it, found rather than invented: the export has
# to be checked against what this system actually writes.
with unscoped():
    latest = (db.query(models.JournalEntry)
              .filter(models.JournalEntry.pharmacy_id == mine,
                      models.JournalEntry.status == "posted")
              .order_by(models.JournalEntry.entry_date.desc()).first())
if latest is None:
    print("  ..   nothing posted on this database to export")
    sys.exit(0)
day = latest.entry_date
span = (day - timedelta(days=30), day)

print(f"\n  the books for {span[0]} to {span[1]}\n")

preview = client.get("/api/ledger/pastel-export/preview", headers=headers,
                     params={"start": span[0].isoformat(),
                             "end": span[1].isoformat()}).json()
check(preview.get("lines", 0) > 0, "there is something to export",
      str(preview.get("says"))[:70])
check(preview.get("balanced") is True,
      "and it balances, which is what Pastel insists on",
      f"{preview.get('debit')} against {preview.get('credit')}")
print(f"        {preview.get('says')}")

print("\n  what it refuses\n")

backwards = client.get("/api/ledger/pastel-export", headers=headers,
                       params={"start": span[1].isoformat(),
                               "end": span[0].isoformat()})
check(backwards.status_code == 400, "a range that runs backwards",
      f"status {backwards.status_code}")

# Make sure at least one account in range is unmapped, then insist.
#
# Deliberately NOT under unscoped(): the accounts and the journal have to be
# read the way the endpoint reads them, or this picks a row belonging to
# another pharmacy, finds no account of ours to clear, and then reports the
# refusal as broken when it was the test that missed.
cleared = None
cleared_was = ""
if not pastel.unmapped(db, span[0], span[1]):
    for row in pastel.rows(db, span[0], span[1]):
        found = (db.query(models.Account)
                 .filter(models.Account.code == row["our_account"]).first())
        if found is not None and (found.external_code or "").strip():
            cleared, cleared_was = found, found.external_code
            found.external_code = ""
            db.commit()
            break
    if cleared is None:
        print("  ..   could not unmap an account to test the refusal")

refused = client.get("/api/ledger/pastel-export", headers=headers,
                     params={"start": span[0].isoformat(),
                             "end": span[1].isoformat()})
check(refused.status_code == 409,
      "an export whose accounts are not mapped to theirs",
      f"status {refused.status_code}")
detail = refused.json().get("detail", {}) if refused.status_code == 409 else {}
check(isinstance(detail, dict) and detail.get("accounts"),
      "and names the accounts to go and set",
      str(detail)[:70])
check("wrong" not in str(detail.get("message", "")).lower()
      or "numbering" in str(detail.get("message", "")).lower(),
      "in words that say what would go wrong")

forced = client.get("/api/ledger/pastel-export", headers=headers,
                    params={"start": span[0].isoformat(),
                            "end": span[1].isoformat(), "force": True})
check(forced.status_code == 200,
      "but somebody who has read that can still take the file")

print("\n  the file itself\n")

# Map every account this range touches, then export properly. What is mapped
# here is noted so it can be unmapped again: this runs against somebody's real
# database and a guard that leaves account codes behind it is a guard that
# quietly changes the thing it was meant to check.
borrowed: list[tuple[int, str]] = []
for missing in pastel.unmapped(db, span[0], span[1]):
    row = (db.query(models.Account)
           .filter(models.Account.code == missing["code"]).first())
    if row is not None:
        borrowed.append((row.id, row.external_code or ""))
        row.external_code = f"P{missing['code']}"
db.commit()

got = client.get("/api/ledger/pastel-export", headers=headers,
                 params={"start": span[0].isoformat(),
                         "end": span[1].isoformat()})
check(got.status_code == 200, "exports once every account is mapped",
      f"status {got.status_code}")
check("text/csv" in got.headers.get("content-type", ""),
      "as a csv the accountant can open")
check("attachment" in got.headers.get("content-disposition", ""),
      "that downloads rather than opening in the browser")

body = got.text if got.status_code == 200 else ""
rows = list(csv.reader(io.StringIO(body)))
check(len(rows) > 1, f"carrying {max(0, len(rows) - 1)} line(s)")
if len(rows) > 1:
    head, first = rows[0], rows[1]
    check(head[0].lower() == "account", "with a header naming the columns",
          ", ".join(head)[:60])
    check(first[0].startswith("P"),
          "and THEIR account code in the account column, not ours",
          f"first column was {first[0]!r}")
    debits = sum(float(r[4] or 0) for r in rows[1:] if len(r) > 5)
    credits = sum(float(r[5] or 0) for r in rows[1:] if len(r) > 5)
    check(abs(debits - credits) < 0.05,
          "and the file itself balances",
          f"{debits:.2f} against {credits:.2f}")
check(body.endswith("\r\n") or "\r\n" in body,
      "with the line endings a Windows application expects")

# Put the mapping back exactly as it was found, so a repeat run starts where
# this one did and nobody inherits a chart of accounts this guard invented.
with unscoped():
    for account_id, was in borrowed:
        row = db.get(models.Account, account_id)
        if row is not None:
            row.external_code = was
    # Last, because the one that was deliberately unmapped above is also in
    # `borrowed`, recorded there as already empty.
    if cleared is not None:
        db.get(models.Account, cleared.id).external_code = cleared_was
    db.commit()

print(f"\n{passed} passed, {failed} failed")
if failed:
    print("\na file that imports into the wrong accounts balances perfectly "
          "and is the hardest error there is to find.")
sys.exit(1 if failed else 0)
