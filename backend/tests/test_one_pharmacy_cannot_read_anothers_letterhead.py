"""The company profile belongs to the pharmacy, not to the install.

`settings` was the only configuration table with no pharmacy on it, and `key`
was globally unique. On a database serving more than one pharmacy that means
there was one `company.trading_name`, one `company.vat_no`, one
`company.bank_account` and one `company.logo` between all of them.

What that does in practice: the second pharmacy to be set up overwrites the
first one's letterhead, and from then on both of them print statements carrying
the same trading name, the same logo and the same bank account. A customer pays
the wrong pharmacy. A tax invoice carries a VAT number belonging to a different
taxpayer.

Nothing looks wrong while it happens. The settings screen shows what was
saved, the PDF renders cleanly, and the only way to find it is for two
customers to compare their invoices.

    python tests/test_one_pharmacy_cannot_read_anothers_letterhead.py
"""
import sys

from snapshot_app import client, sql

ok = True


def check(cond, label, extra=""):
    global ok
    ok = ok and bool(cond)
    print(f"{'ok  ' if cond else 'FAIL'}  {label}{'   ' + str(extra) if extra else ''}")


c = client()

# ---- the schema says who a row belongs to ---------------------------------
columns = [r[1] for r in sql("pragma table_info(settings)")]
check("pharmacy_id" in columns,
      "a settings row says which pharmacy it belongs to", ", ".join(columns))

indexes = sql("pragma index_list(settings)")
unique = [(r[1], r[2]) for r in indexes if r[2]]
on_key_alone = []
for name, _ in unique:
    cols = [r[2] for r in sql(f"pragma index_info('{name}')")]
    if cols == ["key"]:
        on_key_alone.append(name)
check(not on_key_alone,
      "no index makes a key unique across every pharmacy",
      ", ".join(on_key_alone) or "none")
check(any([r[2] for r in sql(f"pragma index_info('{n}')")] == ["pharmacy_id", "key"]
          for n, _ in unique),
      "one value per key PER PHARMACY is enforced")

# ---- and nothing is left ownerless ----------------------------------------
orphans = sql("select count(*) from settings where pharmacy_id is null")[0][0]
check(orphans == 0, "every settings row has an owner", f"{orphans} without one")

# ---- an identity is not COPIED between pharmacies --------------------------
# Two pharmacies each holding their own company.trading_name is the point of
# this change, not a fault, so the count of rows per key proves nothing. What
# must not happen is two of them holding the same VALUE for something that
# identifies one business: that is the backfill having spread an identity, or
# the old shared row surviving under two owners.
#
# Only the keys that name or bank a specific business. Two pharmacies are
# perfectly entitled to share a city, a country or a phone number on a
# switchboard, and asserting otherwise would fail on the truth.
IDENTIFYING = ("company.trading_name", "company.legal_name", "company.vat_no",
               "company.tax_no", "company.registration_no",
               "company.bank_account")
copied = sql("""select key, value, count(distinct pharmacy_id) n from settings
                 where key in ({}) and coalesce(value, '') <> ''
                 group by key, value having n > 1""".format(
                     ", ".join(f"'{k}'" for k in IDENTIFYING)))
check(not copied,
      "no two pharmacies share a trading name, tax number or bank account",
      ", ".join(f"{k}={v!r} x{n}" for k, v, n in copied) or "none shared")

# ---- what the signed-in pharmacy actually reads back ----------------------
r = c.get("/api/profile/company")
check(r.status_code == 200, "the company profile reads back", r.status_code)
if r.status_code == 200:
    fields = {f["key"]: f["value"] for f in r.json().get("fields", [])}
    mine = sql("""select value from settings
                   where key = 'company.trading_name'
                     and pharmacy_id = (select pharmacy_id from users
                                         where username = 'admin' limit 1)""")
    said = fields.get("trading_name", "")
    check(not mine or said == mine[0][0],
          "and it is this pharmacy's own, not whichever was saved last",
          f"read {said!r}")

print()
print("a pharmacy's letterhead is its own." if ok else "FAILED")
sys.exit(0 if ok else 1)
