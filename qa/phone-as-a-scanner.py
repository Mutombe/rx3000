"""Lending a phone to a counter: does it work, and what can it reach?

A pharmacy that has not bought a scanner for every station still has a camera
in everybody's pocket. Pairing one to a workstation is a convenience. The part
worth testing is not the convenience.

WHAT IS ACTUALLY AT STAKE

The phone is deliberately a dumb input device. It sends a string and is told
"sent"; it never learns the patient, the medicine or the script. That is the
whole security design, and it is only true for as long as nobody widens the
token. So this checks what the phone CANNOT do at least as carefully as what
it can: that its token opens nothing else, that it cannot be edited to point
at another counter's pairing, that a code cannot be claimed twice, and that
ending a pairing actually ends it.

A phone left on a counter should be able to put a code onto one screen a
pharmacist is looking at, and nothing else.
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from fastapi.testclient import TestClient          # noqa: E402

from app.main import app                           # noqa: E402
from app.database import SessionLocal              # noqa: E402
from app.tenancy import unscoped, set_current_pharmacy   # noqa: E402
from app import auth, models                       # noqa: E402
from app.services import portal_tokens, scanner_link      # noqa: E402

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

with unscoped():
    me = (db.query(models.User)
          .filter(models.User.is_demo.is_(False), models.User.active,
                  models.User.pharmacy_id.isnot(None)).first())
    if me is None:
        print("  ..   no account on this database")
        sys.exit(0)
    mine = {"Authorization": f"Bearer {auth.create_token(me, db)}"}
    # Somebody else, at another counter. Their pairing must be untouchable.
    them = (db.query(models.User)
            .filter(models.User.id != me.id, models.User.active,
                    models.User.pharmacy_id.isnot(None)).first())
    theirs = ({"Authorization": f"Bearer {auth.create_token(them, db)}"}
              if them else None)

print("\n  pairing\n")

offer = client.post("/api/scanner/pair", headers=mine,
                    json={"station": "Dispensing 2"})
check(offer.status_code == 200, "a counter can ask for a code",
      f"status {offer.status_code}")
code = offer.json().get("code", "")
check(len(code) == 6, "and gets a short one to show", f"code={code!r}")
check(offer.json().get("status") == "pending",
      "which is not paired to anything yet")

again = client.post("/api/scanner/pair", headers=mine,
                    json={"station": "Dispensing 2"})
check(again.json().get("code") == code,
      "asking twice shows the same code rather than collecting pairings")

took = client.post("/api/scanner/claim",
                   json={"code": code, "device": "Test phone"})
check(took.status_code == 200, "a phone can claim it",
      f"status {took.status_code} {str(took.json())[:70]}")
token = took.json().get("token", "")
check(bool(token), "and is given a token of its own")
check(took.json().get("station") == "Dispensing 2",
      "and is told which counter it is serving")

twice = client.post("/api/scanner/claim", json={"code": code})
check(twice.status_code == 409,
      "a second phone cannot claim the same code", f"status {twice.status_code}")

print("\n  scanning\n")

phone = {"X-Scanner": token}
sent = client.post("/api/scanner/scan", headers=phone,
                   json={"code": "RX260900001"})
check(sent.status_code == 200, "the phone can send a scan",
      f"status {sent.status_code} {str(sent.json())[:60]}")
check("code" not in sent.json() and "prescription" not in sent.json()
      and "product" not in sent.json(),
      "and is told only that it arrived, never what it was",
      str(sent.json())[:80])

with unscoped():
    link_id = took.json()["id"]
    link = db.get(models.ScannerLink, link_id)
    queued = scanner_link.waiting(db, link)
check(len(queued) == 1 and queued[0].code == "RX260900001",
      "the counter has it waiting", f"{len(queued)} row(s)")

print("\n  what the phone cannot do\n")

for what, path in [("read a patient", "/api/patients"),
                   ("read the catalogue", "/api/products"),
                   ("resolve a scan itself", "/api/scan"),
                   ("read a script", "/api/prescriptions")]:
    got = (client.post(path, headers=phone, json={"code": "x"})
           if path == "/api/scan" else client.get(path, headers=phone))
    check(got.status_code in (401, 403, 422),
          f"its token cannot {what}", f"status {got.status_code}")

# The one that matters most: the token names a link INSIDE its own signature,
# so it cannot be edited to point at another counter.
if theirs:
    other = client.post("/api/scanner/pair", headers=theirs,
                        json={"station": "Till 1"})
    other_id = other.json()["id"]
    forged = portal_tokens.issue(kind=scanner_link.TOKEN_KIND,
                                 subject_id=other_id, ttl=60)
    # Signed by this same server, so this is the strongest version of the
    # question: even a correctly signed token for an UNCLAIMED pairing is
    # refused, because the pairing is not live.
    used = client.post("/api/scanner/scan", headers={"X-Scanner": forged},
                       json={"code": "RX1"})
    check(used.status_code == 401,
          "a token for a pairing nobody has claimed is refused",
          f"status {used.status_code}")

    stolen = client.get(f"/api/scanner/stream/{other_id}", headers=mine)
    check(stolen.status_code == 404,
          "and one counter cannot watch another counter's scanner",
          f"status {stolen.status_code}")

print("\n  ending it\n")

shut = client.post(f"/api/scanner/close/{link_id}", headers=mine)
check(shut.status_code == 200, "the counter can unpair the phone")
after = client.post("/api/scanner/scan", headers=phone, json={"code": "RX2"})
check(after.status_code == 401,
      "and the phone's next scan is refused", f"status {after.status_code}")

print(f"\n{passed} passed, {failed} failed")
if failed:
    print("\na phone borrowed as a scanner must be able to type into one "
          "screen and read nothing.")
sys.exit(1 if failed else 0)
