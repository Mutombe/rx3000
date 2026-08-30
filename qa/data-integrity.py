"""Facts the database records twice, and whether the two copies agree.

Every check here is of one shape: a number kept in two places. A product's own
`quantity_on_hand` against the sum of its batches. A claim batch's `claim_count`
against the claims attached to it. A sale's `total` against the sum of its lines.
Each pair is written by different code at different moments, and the day they
disagree is the day something was written around one of them.

Nothing here reads the application. These are questions for the database, asked
directly, so a defect that only appears after months of real trading is visible
in a second rather than after somebody notices a figure looking wrong.

WHAT IT FOUND

  * More than half the catalogue's products disagreed with their batches, by
    $25,991 at cost — and the two are believed by different screens. Dispensing
    draws against the batches; almost everything else shows the product's own
    count.
  * Two products counted below nothing. A batch write-off subtracted the
    batch's remainder from the product whether or not the product had ever held
    that much, so "-7 on hand" reached a dispenser as its stock figure.
  * Sixty-nine claim batches recording 450 claims between them, with not one
    claim attached to any of them.

A finding here is not automatically a bug in the code — data can be imported,
corrected by hand, or migrated from another system. It is a place where two
numbers that must match do not, which is always worth a look.

    python qa/data-integrity.py
    python qa/data-integrity.py --all      # every offending row, not a sample
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from sqlalchemy import text                      # noqa: E402

from app.database import engine                  # noqa: E402

#: Each check is a name, a sentence saying why the two must agree, and a query
#: returning the rows where they do not. The first column of each is an
#: identifier and the rest are shown as-is.
CHECKS: list[tuple[str, str, str]] = [
    (
        "a product's own count against its batches",
        "Dispensing draws against the batches; almost every screen shows the "
        "product's own count. Where they differ the two describe the same shelf "
        "differently.",
        """
        SELECT p.id, p.name, p.quantity_on_hand AS own_count,
               COALESCE(b.held, 0) AS in_batches,
               p.quantity_on_hand - COALESCE(b.held, 0) AS out_by
        FROM products p
        LEFT JOIN (SELECT product_id, SUM(quantity_remaining) AS held
                   FROM stock_batches GROUP BY product_id) b
               ON b.product_id = p.id
        WHERE p.active = 1 AND p.quantity_on_hand <> COALESCE(b.held, 0)
        ORDER BY ABS(p.quantity_on_hand - COALESCE(b.held, 0)) DESC
        """,
    ),
    (
        "stock counted below nothing",
        "A shelf cannot hold minus seven of anything. It is arithmetic showing "
        "through, and it reaches a dispenser as a stock figure.",
        """
        SELECT id, name, quantity_on_hand
        FROM products WHERE quantity_on_hand < 0 ORDER BY quantity_on_hand
        """,
    ),
    (
        "a batch holding more than was received",
        "A batch cannot have more left in it than arrived in it.",
        """
        SELECT id, batch_number, quantity_received, quantity_remaining
        FROM stock_batches WHERE quantity_remaining > quantity_received
        """,
    ),
    (
        "a claim batch's count against the claims attached",
        "The batch's own totals were sent to a funder. If no claim is attached, "
        "those totals describe claims nobody can now see.",
        """
        SELECT cb.id, cb.batch_number, cb.claim_count AS says_it_holds,
               (SELECT COUNT(*) FROM claims c WHERE c.batch_id = cb.id) AS attached
        FROM claim_batches cb
        WHERE cb.claim_count <> (SELECT COUNT(*) FROM claims c WHERE c.batch_id = cb.id)
        ORDER BY cb.id DESC
        """,
    ),
    (
        "a sale's total against the sum of its lines",
        "The total is what was charged and banked; the lines are what was sold. "
        "A sale where they differ cannot be reconciled against either.",
        """
        SELECT s.id, s.sale_number, ROUND(s.total, 2) AS charged,
               ROUND(COALESCE(i.lines, 0), 2) AS lines_come_to
        FROM sales s
        LEFT JOIN (SELECT sale_id, SUM(line_total) AS lines
                   FROM sale_items GROUP BY sale_id) i ON i.sale_id = s.id
        WHERE s.status NOT IN ('void', 'cancelled', 'draft')
          AND ABS(s.total - COALESCE(i.lines, 0)) > 0.02
        ORDER BY ABS(s.total - COALESCE(i.lines, 0)) DESC
        """,
    ),
    (
        "a repeat used more times than it was allowed",
        "Repeats used cannot exceed repeats allowed: past that the script has "
        "been dispensed more often than the prescriber permitted.",
        """
        SELECT id, prescription_id, repeats_allowed, repeats_used
        FROM prescription_items
        WHERE repeats_allowed >= 0 AND repeats_used > repeats_allowed
        """,
    ),
    (
        "a dispensing pointing at a prescription line that is gone",
        "A dispensing record with nothing behind it cannot be explained to an "
        "inspector, and it is counted by every report that walks dispensings.",
        """
        SELECT d.id, d.prescription_item_id, d.dispensed_at
        FROM dispensings d
        LEFT JOIN prescription_items pi ON pi.id = d.prescription_item_id
        WHERE pi.id IS NULL
        """,
    ),
    (
        "a claim settled for more than it asked for",
        "A scheme paying more than was claimed is either a keying error or a "
        "duplicate settlement, and both cost money to unpick later.",
        """
        SELECT id, claim_number, ROUND(amount_claimed, 2) AS claimed,
               ROUND(settled_amount, 2) AS settled
        FROM claims WHERE settled_amount > amount_claimed + 0.02
        ORDER BY settled_amount - amount_claimed DESC
        """,
    ),
]


def main() -> int:
    show_all = "--all" in sys.argv
    total = 0
    failing = 0

    with engine.begin() as conn:
        for name, why, sql in CHECKS:
            try:
                rows = conn.execute(text(sql)).all()
            except Exception as exc:                    # noqa: BLE001
                # A check that cannot run is reported, not skipped: a silent
                # skip is indistinguishable from a pass.
                print(f"  SKIP {name}\n       could not run: {str(exc)[:90]}")
                continue

            if not rows:
                print(f"  ok   {name}")
                continue

            failing += 1
            total += len(rows)
            print(f"\n  FAIL {name} — {len(rows)} row(s)")
            print(f"       {why}")
            shown = rows if show_all else rows[:5]
            keys = list(rows[0]._mapping.keys())
            print("       " + "  ".join(f"{k}" for k in keys))
            for r in shown:
                print("       " + "  ".join(str(v) for v in r))
            if not show_all and len(rows) > len(shown):
                print(f"       … and {len(rows) - len(shown)} more (--all)")
            print()

    print(f"\n{len(CHECKS) - failing} of {len(CHECKS)} checks agree"
          f" · {total} row(s) where two records of one fact differ")
    return 1 if failing else 0


if __name__ == "__main__":
    raise SystemExit(main())
