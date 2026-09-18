"""Moving stock between shops takes it off one shelf and puts it on the other.

The feature existed and worked in the happy case. What it did not have was any
of the things that stop it going wrong, and every one of those is checked here
against a copy of the real database.

  - it costs a permission. Any signed-in account could move any branch's stock
    to any other branch and book it in again, and nothing on the screen would
    have looked wrong.
  - it crosses branches. A transfer is by definition work about two shops, but
    the batch query ran under the caller's own branch filter, so despatching
    from anywhere except the branch you were standing in reported "that branch
    holds 0" however full its shelf was.
  - receiving it twice books it in once. The status check and the commit were
    not serialised, so two people confirming the same arrival both passed the
    check and the shop ended up with twice what turned up.
  - the ledger says what happened. `balance_after` was read after the new
    batches were added, so autoflush counted them and the movement recorded a
    balance the shelf never held.

    python tests/test_stock_moves_between_branches.py
"""
import sys

from snapshot_app import client, execute, sql

ok = True


def check(cond, label, extra=""):
    global ok
    ok = ok and bool(cond)
    print(f"{'ok  ' if cond else 'FAIL'}  {label}{'   ' + str(extra) if extra else ''}")


def held(product_id, branch_id):
    got = sql("""select coalesce(sum(quantity_remaining), 0) from stock_batches
                  where product_id = ? and branch_id = ?""", (product_id, branch_id))
    return int(got[0][0] or 0)


def run():
    c = client()

    branches = sql("select id, name from branches where active = 1 order by id")
    check(len(branches) >= 2, "there are two branches to move stock between",
          ", ".join(b[1] for b in branches[:3]))
    if len(branches) < 2:
        return
    here, there = int(branches[0][0]), int(branches[1][0])

    row = sql("""select p.id, p.name from products p
                   join stock_batches b on b.product_id = p.id
                  where b.branch_id = ? and b.quantity_remaining >= 5 and p.active = 1
                  group by p.id limit 1""", (here,))
    check(bool(row), "and a product with stock on the first one")
    if not row:
        return
    product, name = int(row[0][0]), row[0][1]

    before_here, before_there = held(product, here), held(product, there)
    print(f"      {name}: {before_here} at branch {here}, {before_there} at branch {there}")

    # ---- it costs a permission --------------------------------------------
    # Driven as somebody who has none: a cashier may sell, and may not move a
    # shop's stock to another shop.
    cashier = sql("select username from users where role = 'cashier' and active = 1 limit 1")
    if cashier:
        # Checked against the same decision the endpoint makes, rather than by
        # signing in as them: the password is not known here and the capability
        # is the thing under test.
        from app.database import SessionLocal
        from app.models import User
        from app.services import permissions
        from app.tenancy import unscoped
        db = SessionLocal()
        with unscoped():
            who = db.query(User).filter(User.username == cashier[0][0]).first()
            allowed = permissions.check(db, who, "stock.transfer").get("allowed")
        db.close()
        check(allowed is False, "a cashier may not move stock between branches")
    else:
        check(True, "no cashier in this database to refuse, skipped")

    # ---- despatch, from a branch the caller is not standing at -------------
    sent = c.post("/api/branches/transfers", json={
        "from_branch_id": here, "to_branch_id": there,
        "product_id": product, "quantity": 5, "notes": "checked by the test"})
    check(sent.status_code == 200, "an administrator can despatch", sent.text[:110])
    if sent.status_code != 200:
        return
    ref = sent.json()["reference"]
    transfer_id = sent.json()["id"]

    check(held(product, here) == before_here - 5,
          "the sending branch is 5 lighter, immediately",
          f"{before_here} to {held(product, here)}")
    check(held(product, there) == before_there,
          "and the receiving branch has not moved yet, because it has not arrived")

    listed = c.get("/api/branches/transfers/in-transit").json()
    check(any(t["reference"] == ref for t in listed),
          "it shows as in transit while it is neither here nor there",
          f"{len(listed)} in transit")

    # ---- receive -----------------------------------------------------------
    got = c.post(f"/api/branches/transfers/{transfer_id}/receive")
    check(got.status_code == 200, "and the other branch can book it in", got.text[:110])
    check(held(product, there) == before_there + 5,
          "the receiving branch is 5 heavier",
          f"{before_there} to {held(product, there)}")
    check(held(product, here) == before_here - 5,
          "and the sending branch did not change again")

    # ---- what the ledger says ---------------------------------------------
    moves = sql("""select movement_type, quantity_delta, balance_after, branch_id
                     from stock_movements where reference = ?
                    order by id""", (ref,))
    kinds = {m[0]: m for m in moves}
    check("transfer_out" in kinds and "transfer_in" in kinds,
          "both halves are written to the ledger", ", ".join(kinds))
    if "transfer_in" in kinds:
        booked = kinds["transfer_in"]
        check(int(booked[1]) == 5, "the arrival is recorded as +5", booked[1])
        check(int(booked[2]) == held(product, there),
              "and its balance is what the shelf actually holds, not double it",
              f"ledger {booked[2]}, shelf {held(product, there)}")

    # ---- receiving twice ---------------------------------------------------
    again = c.post(f"/api/branches/transfers/{transfer_id}/receive")
    check(again.status_code >= 400, "receiving it a second time is refused",
          again.status_code)
    check(held(product, there) == before_there + 5,
          "and the stock did not arrive twice", held(product, there))

    # ---- and the obvious refusals -----------------------------------------
    same = c.post("/api/branches/transfers", json={
        "from_branch_id": here, "to_branch_id": here,
        "product_id": product, "quantity": 1})
    check(same.status_code >= 400, "a branch cannot send stock to itself")
    too_much = c.post("/api/branches/transfers", json={
        "from_branch_id": here, "to_branch_id": there,
        "product_id": product, "quantity": 10_000_000})
    check(too_much.status_code >= 400, "and cannot send more than it holds")


if __name__ == "__main__":
    try:
        run()
    except Exception as exc:                  # noqa: BLE001
        import os
        import traceback
        traceback.print_exc()
        print("FAIL", exc)
        sys.stdout.flush()
        os._exit(1)
    print("\nall passed" if ok else "\nFAILURES")
    sys.exit(0 if ok else 1)
