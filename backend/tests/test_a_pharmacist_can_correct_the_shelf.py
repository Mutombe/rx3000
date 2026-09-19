"""Who may correct a shelf, and who may not.

The pharmacist is the person standing at the shelf with the box in their hand.
Until now `stock.adjust` was admin and manager only, so the one member of staff
who can SEE that the count is wrong had to find a manager to say so. A
correction nobody can make at the moment they notice it is a correction that
does not get made, and the figure stays wrong until a stock take finds it.

Widening it is only safe because of the two things checked here alongside it:
the accountant still cannot, because whoever checks a number must not be able
to change it, and the cashier still cannot, because a till operator correcting
stock is how shrinkage is covered up rather than found.

    python tests/test_a_pharmacist_can_correct_the_shelf.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import permissions  # noqa: E402

ok = True


def check(cond, label, extra=""):
    global ok
    ok = ok and bool(cond)
    print(f"{'ok  ' if cond else 'FAIL'}  {label}{'   ' + str(extra) if extra else ''}")


# ---- the shelf ------------------------------------------------------------
check(permissions.role_has("pharmacist", "stock.adjust"),
      "a pharmacist may correct a count")
check(permissions.role_has("manager", "stock.adjust"),
      "and so may a manager")
check(permissions.role_has("admin", "stock.adjust"),
      "and so may an administrator")

# ---- and who still may not ------------------------------------------------
check(not permissions.role_has("cashier", "stock.adjust"),
      "a cashier may not: a till operator correcting stock is how shrinkage is "
      "covered up rather than found")
check("stock.adjust" in permissions.ACCOUNTANT_WITHHELD,
      "an accountant may not: whoever checks a number must not be able to change it")

# ---- and what widening this did NOT widen ---------------------------------
# A correction is not a write-off. Expired, damaged and recalled stock leaving
# the building is a different act with a different record behind it, and the
# pharmacist has not been given that here.
check(not permissions.role_has("pharmacist", "stock.write_off"),
      "writing stock off is still a manager's act, not a pharmacist's")
check(not permissions.role_has("pharmacist", "stock.deactivate"),
      "and taking a product code out of use across the group is still the administrator's")

# ---- the capability is real ------------------------------------------------
names = [c[0] for c in permissions.CAPABILITIES]
check(names.count("stock.adjust") == 1,
      "stock.adjust is declared exactly once", f"{names.count('stock.adjust')} time(s)")

print()
print("the shelf can be corrected by the person standing at it." if ok else "FAILED")
sys.exit(0 if ok else 1)
