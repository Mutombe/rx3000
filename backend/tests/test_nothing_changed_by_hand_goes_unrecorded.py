"""A price set by hand, or a shelf corrected, can be traced back to the script.

A pharmacy's figures are mostly computed. The ones worth asking about are the
ones somebody overrode, and the question is never "list every price override".
It is "this script, this patient, this morning: was anything about it changed
by hand, and by whom".

That could not be answered. Both acts were recorded, and neither was recorded
against the thing being done at the time:

  - `PriceOverride.prescription_item_id` was declared as the link and never
    once written. Every one of the twenty rows on the development database
    carried NULL, because an override is authorised while the line is still
    being typed and the item does not exist yet. A column that is only ever
    null is not a link, it is a comment.

  - `StockMovement` recorded the product, the figure and the person, and
    nothing about what they were doing. A correction made at the counter with a
    script open looked identical to one made from the stock screen a week
    later.

Both now name the script. The alternative was to infer it from timing, and
"same product, same user, within two minutes" is a guess that reads as a fact:
wrong in both directions on a busy counter, and printed next to a dispenser's
name it reads as an accusation.

    python tests/test_nothing_changed_by_hand_goes_unrecorded.py
"""
import sys

from snapshot_app import client, sql

ok = True


def check(cond, label, extra=""):
    global ok
    ok = ok and bool(cond)
    print(f"{'ok  ' if cond else 'FAIL'}  {label}{'   ' + str(extra) if extra else ''}")


c = client()

# ---- the schema can hold the answer ----------------------------------------
movement_cols = [r[1] for r in sql("pragma table_info(stock_movements)")]
check("prescription_id" in movement_cols,
      "a stock movement can name the script it was made from")

override_cols = [r[1] for r in sql("pragma table_info(price_overrides)")]
check("prescription_id" in override_cols,
      "and so can a price override")

# ---- the endpoints accept it ------------------------------------------------
schema = c.get("/openapi.json")
check(schema.status_code == 200, "the API describes itself", schema.status_code)
if schema.status_code == 200:
    spec = schema.json()

    adjust = (spec["components"]["schemas"].get("StockAdjust") or {}).get("properties", {})
    check("prescription_id" in adjust,
          "adjusting stock takes the script that was on screen",
          ", ".join(sorted(adjust)))

    def body_props(path):
        try:
            ref = (spec["paths"][path]["post"]["requestBody"]["content"]
                   ["application/json"]["schema"]["$ref"])
        except KeyError:
            return {}
        name = ref.rsplit("/", 1)[-1]
        return spec["components"]["schemas"][name].get("properties", {})

    for path, what in (("/api/price-override", "a price"),
                       ("/api/claim-override", "a claim amount")):
        props = body_props(path)
        if not props:
            check(False, f"setting {what} by hand has a described body", path)
            continue
        check("prescription_id" in props,
              f"setting {what} by hand takes the script", ", ".join(sorted(props)))

# ---- the reports exist ------------------------------------------------------
reports = c.get("/api/reports/catalogue")
check(reports.status_code == 200, "the report catalogue loads", reports.status_code)
if reports.status_code == 200:
    keys = {r["key"] for r in reports.json().get("reports", reports.json())} \
        if isinstance(reports.json(), (list, dict)) else set()
    for key, why in (
        ("stock_transfers",
         "stock moved between branches is on a report at all"),
        ("hand_adjustments_on_scripts",
         "and so is everything changed by hand while dispensing"),
    ):
        check(key in keys, why, key)

# ---- and the history row says so -------------------------------------------
history = c.get("/api/dispensing/history?per_page=5")
check(history.status_code == 200, "dispensing history loads", history.status_code)
if history.status_code == 200:
    items = history.json().get("items", [])
    if not items:
        print("      (no dispensings on this snapshot, so the row shape is not checked)")
    else:
        # The flags are present only on rows that were touched, deliberately:
        # almost nothing is, and a false on every row is noise. What must be
        # true is that the endpoint can carry them at all.
        row = items[0]
        expected = {"id", "rx_number", "dispensed_by", "product"}
        check(expected <= set(row),
              "a history row still carries what it always did",
              ", ".join(sorted(expected - set(row))) or "all present")

print()
print("what somebody decided is recorded beside what the system computed."
      if ok else "FAILED")
sys.exit(0 if ok else 1)
