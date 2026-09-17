"""A dispensed box can say which pharmacy handed it over, and under what law.

Two things about the foot of a dispensing label, both of which have been wrong.

WHERE IT CAME FROM. The shop's name and street were taken off to save three
lines on a small sticker, on the reasoning that the bag it goes into already
says so. A bag is not what a patient still has at ten at night. A box that
cannot say where it came from is a box nobody can query, return or ring about,
and the label is the only part of the transaction that goes home with them.

WHAT IT IS. The sticker printed `S{schedule}`. That number is an internal
ordinal, not a classification: schedule 4 is "S4" in South Africa and "PP" in
Zimbabwe. So a Harare pharmacy was printing a South African classification on a
box it hands to a patient, which is both wrong and the kind of wrong nobody
reports, because "S4" looks like a real thing to see on a label.

Against a snapshot of the local database:

  - the label carries the shop, its street and its telephone
  - and the schedule the law here uses, not the ordinal
  - the printed sheet puts the shop above the telephone, in that order
  - the roll label does too
  - a pharmacy with nothing recorded prints nothing, never a placeholder

  python tests/test_the_label_says_where_it_came_from.py
"""
import pathlib
import sys

from snapshot_app import client

ROOT = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src"


def a_label(c):
    for rx in c.get("/api/prescriptions?limit=10").json():
        labels = c.get(f"/api/prescriptions/{rx['id']}/labels").json()
        if labels:
            return labels[0]
    raise AssertionError("the snapshot has no dispensed script to label")


def run():
    c = client()
    label = a_label(c)

    for field in ("branch_name", "branch_address", "branch_phone"):
        assert label.get(field), f"the label carries no {field}: {label.get(field)!r}"
    print(f"ok    the shop is on it: {label['branch_name']}, {label['branch_address']}")
    print(f"ok    so is the number to ring: {label['branch_phone']}")

    # The classification, not the ordinal.
    assert label.get("schedule_code"), "the label carries no schedule code"
    assert not label["schedule_code"].startswith("S") or label["schedule_code"] == "SR", (
        f"the label says {label['schedule_code']!r}, which is the South African "
        "form. This jurisdiction's codes come off the pack in jurisdictions.py")
    print(f"ok    and the classification the law here uses: schedule "
          f"{label['schedule']} prints as {label['schedule_code']}")

    # ---- the printed sheet -------------------------------------------------
    sheet = (ROOT / "print.ts").read_text(encoding="utf-8")
    foot = sheet[sheet.index('<div class="foot">'):sheet.index("</div>`;", sheet.index('<div class="foot">'))]
    for must in ("branch_name", "branch_address", "Tel:"):
        assert must in foot, f"the printed foot has no {must}"
    # In that order, because that is the order the questions come in.
    assert foot.index("branch_name") < foot.index("branch_address") < foot.index("Tel:"), (
        "the foot does not read shop, street, telephone")
    print("ok    the printed sheet reads shop, then street, then the telephone")

    assert "schedule_code" in sheet, "the sheet still prints the schedule ordinal"
    assert 'class="sched"' in sheet
    print("ok    …and prints the schedule code on the sticker")

    # ---- the roll ----------------------------------------------------------
    roll = (ROOT / "deviceAgent.ts").read_text(encoding="utf-8")
    tail = roll[roll.index("Whose pharmacy dispensed it"):]
    tail = tail[:tail.index("return lines;")]
    for must in ("branch_name", "branch_address", "Tel:"):
        assert must in tail, f"the roll label has no {must}"
    assert tail.index("branch_name") < tail.index("branch_address") < tail.index("Tel:"), (
        "the roll foot does not read shop, street, telephone")
    print("ok    the roll label does the same")

    # ---- and nothing is invented -------------------------------------------
    # Every one of them is written as "if we have it, print it". A label for a
    # pharmacy that never filled in an address must print no address, not the
    # software's idea of one.
    for guard in ("(l.branch_name || l.pharmacy_name)", "(l.branch_address || l.pharmacy_address)"):
        assert guard in sheet, f"the sheet prints {guard} unconditionally"
    assert "if (who)" in roll and "if (where)" in roll, "the roll prints them unconditionally"
    print("ok    nothing recorded prints nothing, never a placeholder")


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
    print("\nall passed")
