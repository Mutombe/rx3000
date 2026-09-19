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

# ---- an identity is not shared --------------------------------------------
# A company.* row is a name, a tax number, an account to be paid into. Two
# pharmacies holding the same one is the bug itself, so it must not happen by
# the backfill having copied them about.
shared = sql("""select key, count(distinct pharmacy_id) n from settings
                 where key like 'company.%' group by key having n > 1""")
check(not shared,
      "no company identity is held by more than one pharmacy",
      ", ".join(f"{k} x{n}" for k, n in shared) or "none shared")

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
