"""RX-Assistant may not read anything the person asking could not read.

This is the whole security model of the assistant, and it is the easiest kind
of hole to ship without noticing: nothing on the screen would look wrong. The
answer would simply contain more than the person was entitled to, phrased
helpfully, and nobody would ever file a bug about being told too much.

So every lookup takes the request's own session and the signed-in user, and
goes through the same capability checks the screens go through. What this pins
down:

  - a cashier is refused the takings, and told which permission it needs
  - a cashier looking up a medicine gets the stock, which they need at the
    counter, and not the price, which is money
  - an administrator gets both
  - a refusal is an ANSWER rather than an error, so the model can relay it

    python tests/test_the_assistant_sees_only_what_you_see.py
"""
import sys

sys.path.insert(0, ".")

from app.database import SessionLocal                        # noqa: E402
from app.models import User                                  # noqa: E402
from app.services import assistant, assistant_data as data   # noqa: E402
from app.services import permissions                         # noqa: E402
from app.tenancy import unscoped                             # noqa: E402

ok = True


def check(cond, label, extra=""):
    global ok
    ok = ok and bool(cond)
    print(f"{'ok  ' if cond else 'FAIL'}  {label}{'   ' + str(extra) if extra else ''}")


def run():
    db = SessionLocal()
    with unscoped():
        admin = db.query(User).filter(User.username == "admin").first()
        cashier = (db.query(User)
                   .filter(User.role == "cashier", User.active.is_(True)).first())
        check(admin is not None, "there is an administrator to test with")
        check(cashier is not None, "and somebody without the money permission")
        if not (admin and cashier):
            return

        # ---- the premise ----------------------------------------------------
        check(permissions.check(db, admin, "reports.money").get("allowed") is True,
              "the administrator may see money")
        check(permissions.check(db, cashier, "reports.money").get("allowed") is False,
              "the cashier may not")

        # ---- the takings ----------------------------------------------------
        mine = data.how_is_trade(db, admin, 7)
        check("refused" not in mine, "the administrator gets the takings",
              f"{mine.get('sales')} sales over {mine.get('over_days')} days")

        theirs = data.how_is_trade(db, cashier, 7)
        check(bool(theirs.get("refused")), "the cashier is refused them")
        check("cashier" in str(theirs.get("refused", "")).lower()
              or "may not" in str(theirs.get("refused", "")).lower(),
              "and told why, in the server's own words",
              str(theirs.get("refused"))[:70])
        check("taken_over_the_period" not in theirs,
              "and the figure is not in the refusal either")

        # ---- a medicine, which both of them need ----------------------------
        # Not all or nothing. A cashier at a counter has to know whether there
        # is any left; that is not the same question as what it cost.
        for who, may_see in ((admin, True), (cashier, False)):
            got = data.look_up_medicine(db, who, "amoxicillin")
            first = (got.get("medicines") or [{}])[0]
            check(got.get("found", 0) > 0, f"{who.username} can look a medicine up",
                  f"{got.get('found')} found")
            check("on_this_shelf" in first,
                  f"and {who.username} sees what is on the shelf")
            check(("price" in first) is may_see,
                  f"and the price is {'shown' if may_see else 'withheld'} for {who.username}")
        withheld = data.look_up_medicine(db, cashier, "amoxicillin")
        check(bool(withheld.get("money_hidden")),
              "the withholding is stated rather than silent",
              str(withheld.get("money_hidden"))[:60])

        # ---- and nothing here writes ----------------------------------------
        # The assistant explains; it does not act. Asserted against the tool
        # list rather than trusted, because the day somebody adds a write tool
        # is the day this stops being true quietly.
        names = [t.get("name") for t in assistant.TOOLS]
        writes = [n for n in names
                  if any(w in n for w in ("set_", "create", "update", "delete",
                                          "adjust", "write", "dispense", "void"))]
        check(not writes, "no tool the assistant has can change anything",
              ", ".join(names))

        # ---- a lookup with nobody to run as must refuse ----------------------
        frames = list(assistant.run("what is running low?", web=False, db=None, user=None))
        said = " ".join(f.get("say", "") for f in frames if f.get("type") == "tool_done")
        check("not available" in said or any(f.get("type") == "error" for f in frames),
              "and with no session, a lookup refuses rather than running unscoped")
    db.close()


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
