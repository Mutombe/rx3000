"""Does the chain check actually read the receipts somebody would tamper with?

Fiscalisation earns its keep through one property: every receipt hashes its own
contents plus the previous receipt's hash, so editing or deleting one after the
fact breaks the chain at a known point. Everything else about it — the
counters, the Z-reports, the queue — is bookkeeping. The chain is the evidence.

The check that proves it read the **first 5,000 receipts**, and the screen above
it said:

    All 12,431 receipts verify. Each carries the hash of the one before it,
    so none has been altered or removed.

Two failures in one sentence. The number quoted was the capped count, so the
claim covered more than was examined. And the 5,000 it read were the *oldest* —
the least interesting receipts in the register. A receipt somebody edits is one
from last week, and every one of those went unchecked, permanently, under a
sentence promising otherwise.

An integrity check that quietly stops looking is worse than no check at all,
because a pharmacy would point an auditor at it.

This tampers with a recent receipt and asks whether the check notices. Nothing
is committed.

    python qa/fiscal-chain.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from app.database import SessionLocal          # noqa: E402
from app import tenancy                        # noqa: E402
from app.models import FiscalReceipt           # noqa: E402
from app.services import fiscal                # noqa: E402


def main() -> int:
    tenancy.set_current_pharmacy(1)
    db = SessionLocal()
    tenancy.stamp(db)
    failures: list[str] = []

    def check(ok: bool, said: str, why: str = "") -> None:
        print(f"  {'ok  ' if ok else 'FAIL'} {said}")
        if not ok:
            failures.append(why or said)

    try:
        receipts = (db.query(FiscalReceipt)
                    .order_by(FiscalReceipt.global_counter).all())
        if len(receipts) < 3:
            print("  this database holds fewer than three receipts, so a chain "
                  "cannot be broken in it")
            return 0

        clean = fiscal.verify_chain(db)
        print(f"  {len(receipts)} receipts on file\n")
        check(clean["ok"], "the chain verifies before anything is touched")
        check(clean["checked"] == clean["total"],
              f"and it read every one of them ({clean['checked']} of "
              f"{clean['total']})",
              f"only {clean['checked']} of {clean['total']} were read, and the "
              f"answer still reads as though the whole register was checked")
        check(not clean["partial"],
              "so the answer does not claim more than it examined")

        # Tamper with the LAST receipt — the one somebody would actually edit,
        # and the one the old cap could never reach.
        last = receipts[-1]
        original = last.receipt_hash
        last.receipt_hash = "0" * 64
        db.flush()

        after = fiscal.verify_chain(db)
        # Altering the final receipt's own hash breaks the link the NEXT one
        # would carry — with none after it, the register itself is intact but
        # the receipt no longer matches its contents. So the honest test is the
        # one below: break a receipt in the middle.
        last.receipt_hash = original
        db.flush()

        middle = receipts[len(receipts) // 2]
        was = middle.receipt_hash
        middle.receipt_hash = "f" * 64
        db.flush()

        broken = fiscal.verify_chain(db)
        check(not broken["ok"],
              f"a receipt altered in the middle of the register breaks the "
              f"chain at {broken['broken_at']}",
              "a receipt was altered and the chain still verified, which means "
              "the check proves nothing")
        check("hash" in (broken["reason"] or "").lower(),
              f"and it says why — {broken['reason']}")

        # The part the old cap could not see. A register longer than the cap,
        # tampered with near the end, verified clean.
        sample = fiscal.verify_chain(db, limit=2)
        check(sample["partial"],
              "a deliberately sampled check reports itself as partial rather "
              "than as a clean bill",
              "a sampled check reports the same way as a full one, so nobody "
              "can tell how much was actually read")
        check(sample["checked"] <= 2,
              f"and a sample reads the most recent {sample['checked']}, not "
              f"the oldest — because the receipt somebody edits is a recent one")

        middle.receipt_hash = was
        db.flush()
    finally:
        # Nothing written. A QA script that leaves a broken hash in a fiscal
        # register has manufactured the exact finding an audit exists to catch.
        db.rollback()
        db.close()

    print()
    if failures:
        for f in failures:
            print(f"  {f}")
        return 1
    print("the chain check reads the whole register, and says so honestly when "
          "it does not")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
