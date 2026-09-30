# -*- coding: utf-8 -*-
"""The money in the finish dialog is the money on the rows above it.

WHAT WAS REPORTED

"When we change the price in the modal that appears after selecting the
medicine, the price does not persist to the Finish modal."

WHAT IT WAS

Two endpoints price the same basket, and only one of them was told.

  /api/script-totals   prices the footer under the script table. It reads
                       `unit_price` off each line and prices through
                       `pricing.price_line`, so the footer showed $4.00.

  /api/claim-estimate  prices the finish dialog: gross, what the scheme pays,
                       and the shortfall the dispenser collects. It built its
                       rows as `(product, quantity)` and dropped `unit_price`
                       and `claim` on the floor, so it quoted the catalogue.

An authorised override therefore reached the row, the till and the claim, and
did not reach the one screen where the dispenser agrees the money with the
patient standing in front of them. A line authorised at $2.00 each showed
$4.33 on the rows and $0.76 in the dialog.

`claims_engine.estimate` says in its own docstring that it prices lines "the
way the sale will be priced, because an estimate that does not agree with the
sale three seconds later is worse than no estimate". That sentence was untrue
for the two figures a dispenser is most likely to have changed.

WHAT THIS MEASURES

Not the wiring. The agreement: for the same basket, the gross from the two
endpoints is the same figure, with a price set by hand, with a claim set by
hand, and with neither. A third endpoint that starts pricing baskets can be
added to `BASKETS` and is then held to the same answer.

IN PROCESS, DELIBERATELY

The first version of this asked a running dev server over HTTP and planted its
fault by editing the router and waiting for `--reload`. That reported the
planted fault as UNCAUGHT twice, and both times the guard was right and the
measurement was wrong: the server had stopped picking up changes, so the plant
was asked of code that was never loaded. A guard whose plant depends on
somebody else's file watcher proves nothing on the day it matters. This one
imports the application, so the fault it plants is the fault it measures.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from fastapi.testclient import TestClient          # noqa: E402

from app.main import app                           # noqa: E402
from app.services import claims_engine             # noqa: E402

#: A cent. Both sides round to two places, so anything above this is a
#: disagreement rather than floating point.
SLACK = 0.005

client = TestClient(app)


def baskets(pid: int) -> list[tuple[str, list[dict]]]:
    return [
        ("off the shelf", [{"product_id": pid, "quantity": 2}]),
        ("a price set by hand",
         [{"product_id": pid, "quantity": 2, "unit_price": 1.5}]),
        ("a price and a claim set by hand",
         [{"product_id": pid, "quantity": 2, "unit_price": 1.5, "claim": 1.0}]),
        ("a blank price, which means the shelf",
         [{"product_id": pid, "quantity": 2, "unit_price": ""}]),
        ("a price on one line of two",
         [{"product_id": pid, "quantity": 2, "unit_price": 1.5},
          {"product_id": pid, "quantity": 1}]),
    ]


def look(head: dict, pid: int) -> list[str]:
    bad = []
    for said, items in baskets(pid):
        totals = client.post("/api/script-totals",
                             json={"items": items, "medical_aid_id": None},
                             headers=head).json()
        split = client.post("/api/claim-estimate",
                            json={"patient_id": None, "items": items},
                            headers=head).json()
        footer = float(totals.get("totals", {}).get("gross", 0.0))
        dialog = float(split.get("total", 0.0))
        if abs(footer - dialog) > SLACK:
            bad.append(f"{said}: the rows add up to {footer:.2f} and the "
                       f"finish dialog says {dialog:.2f}")

    # And the one that is not a disagreement between two endpoints but a
    # disagreement with the request. Both could be quoting the catalogue and
    # agreeing with each other about it, which is the fault this was written
    # for, seen from the other side.
    hand = client.post("/api/claim-estimate",
                       json={"patient_id": None,
                             "items": [{"product_id": pid, "quantity": 2,
                                        "unit_price": 1.5}]},
                       headers=head).json()
    if abs(float(hand.get("total", 0)) - 3.0) > SLACK:
        bad.append(f"a line of 2 authorised at 1.50 each should come to 3.00, "
                   f"and the finish dialog says "
                   f"{float(hand.get('total', 0)):.2f}")
    return bad


def sign_in() -> tuple[dict, int]:
    login = client.post("/api/auth/login",
                        json={"username": "admin", "password": "admin123"})
    if login.status_code != 200:
        raise SystemExit(f"could not sign in ({login.status_code})")
    head = {"Authorization": f"Bearer {login.json()['access_token']}"}
    body = client.get("/api/products?limit=1", headers=head).json()
    rows = body if isinstance(body, list) else (
        body.get("items") or body.get("rows") or [])
    if not rows:
        raise SystemExit("The catalogue is empty, so there is nothing to price.")
    return head, int(rows[0]["id"])


def report() -> int:
    head, pid = sign_in()
    bad = look(head, pid)
    if not bad:
        print("ok  the finish dialog and the script's own footer price the "
              "same basket the same way, with a price set by hand, with a "
              "claim set by hand, and with neither")
        return 0
    print(f"\nFAIL  {len(bad)} disagreement(s) about the same basket\n")
    for line in bad:
        print("  " + line)
    print("\n  An estimate that does not agree with the sale three seconds")
    print("  later is worse than no estimate.")
    return 1


def plant() -> int:
    """Put the fault back exactly where it lived: at the seam.

    The router used to hand `estimate` two-tuples, so everything the dispenser
    had set by hand was gone before the engine saw it. Truncating the lines
    here is that, and nothing else about the two endpoints changes.
    """
    head, pid = sign_in()
    real = claims_engine.estimate
    claims_engine.estimate = (
        lambda db, patient, lines: real(db, patient,
                                        [(row[0], row[1]) for row in lines]))
    try:
        bad = look(head, pid)
        if not bad:
            print("FAIL  the hand set price and claim were dropped before the "
                  "engine saw them, and this said nothing")
            return 1
        print(f"ok  planted fault caught: {bad[0]}")
        return 0
    finally:
        claims_engine.estimate = real


if __name__ == "__main__":
    sys.exit(plant() if "--plant" in sys.argv else report())
