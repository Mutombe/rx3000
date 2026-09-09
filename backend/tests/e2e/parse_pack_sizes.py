"""Read the pack sizes that are written the way a pharmacy writes them.

The first pass only understood a bare number, so `1000` was parsed and `30s`
was not — and `30s` is how a pack of thirty is written on every shelf label in
the country. 316 products kept `units_per_pack = 1`, which meant every screen
went on multiplying a pack price by a tablet count for them.

That is the repeats page: Atazanavir/Ritonavir, a pack of 30 at $22, sixty
tablets on the script, shown as $1,320 instead of $44.

THE RULE, AND WHERE IT REFUSES TO GUESS

A pack size answers one question: how many dispensable units come out of one
box? That depends on what the thing is, and the pack string says which.

  30s, 24s, 100s        thirty tablets out of a box. The count IS the answer.
  30 tabs, 60 caps      the same, said longer.

  100ml, 500g, 10ml     ONE. A bottle of syrup is dispensed as a bottle — the
                        patient gets the bottle, not a hundred millilitres of
                        loose liquid, and the price on it is the price of the
                        bottle. Reading 100ml as a hundred units would divide
                        a correct price by a hundred, which is the same bug
                        pointing the other way and much harder to notice.

  200 doses             ONE, for the same reason. An inhaler is dispensed as an
                        inhaler even though the canister holds two hundred
                        actuations.

  anything else         ONE, which changes nothing.

Every uncertain case resolves to 1, and 1 is the value that leaves a product
behaving exactly as it does today. The tool can only make a figure smaller by
recognising something, never by guessing.
"""
import os
import pathlib
import re
import sys

BACKEND = pathlib.Path(r"C:\Users\PC\documents\rx3000\backend")
env = (BACKEND / ".env").read_text(encoding="utf-8")
os.environ["DATABASE_URL"] = re.search(
    r"^SEED_TARGET_URL=(.+)$", env, re.M).group(1).strip()

from sqlalchemy import create_engine, text                # noqa: E402

#: Units of measure. A pack described by volume or weight is one container.
MEASURE = re.compile(r"\b\d+\s*(ml|l|litre|liter|g|kg|mg|mcg|iu|%)\b", re.I)
#: A number of doses in one device — still one device.
DEVICE = re.compile(r"\b(dose|doses|puff|puffs|actuation|spray|sprays)\b", re.I)
#: "30s", "30 s", "30 tabs", "60 capsules", "12 sachets".
COUNT = re.compile(
    r"^\s*(\d{1,5})\s*(s|tab|tabs|tablet|tablets|cap|caps|capsule|capsules|"
    r"sachet|sachets|supp|supps|suppository|suppositories|pcs|pieces|units?)?\s*$",
    re.I)


def units_in(pack: str) -> int:
    """How many dispensable units come out of one pack. 1 when unsure."""
    text_ = (pack or "").strip()
    if not text_:
        return 1
    # A measure or a device is one container, whatever number is on it.
    if MEASURE.search(text_) or DEVICE.search(text_):
        return 1
    m = COUNT.match(text_)
    if not m:
        return 1
    n = int(m.group(1))
    # A pack of one is a pack of one, and a five-figure "pack" is a typo or a
    # bulk code rather than a box somebody opens.
    return n if 1 < n <= 10000 else 1


DRY = "--write" not in sys.argv
engine = create_engine(os.environ["DATABASE_URL"])

with engine.begin() as c:
    rows = c.execute(text("""
        select id, pharmacy_id, name, coalesce(pack_size,'') pack,
               coalesce(units_per_pack,1) upp, coalesce(unit_price,0) price
        from products
        where coalesce(units_per_pack,1) = 1 and coalesce(pack_size,'') <> ''
    """)).fetchall()

    change = [(r, units_in(r.pack)) for r in rows]
    change = [(r, n) for r, n in change if n > 1]

    print(f"  {len(rows):,} products have a pack string and units_per_pack = 1")
    print(f"  {len(change):,} of them are readable as a count\n")

    seen = {}
    for r, n in change:
        seen.setdefault(r.pack, [0, n])[0] += 1
    for pack, (cnt, n) in sorted(seen.items(), key=lambda x: -x[1][0])[:14]:
        print(f"    {cnt:>5,}  {pack!r:14} -> {n} units per pack")

    unread = {}
    for r in rows:
        if units_in(r.pack) == 1:
            unread.setdefault(r.pack, 0)
            unread[r.pack] += 1
    print(f"\n  left at 1 (a container, or unreadable): "
          f"{sum(unread.values()):,} products")
    for pack, cnt in sorted(unread.items(), key=lambda x: -x[1])[:10]:
        print(f"    {cnt:>5,}  {pack!r}")

    if DRY:
        print("\n  (dry run — nothing written. pass --write)")
        raise SystemExit(0)

    for r, n in change:
        c.execute(text("update products set units_per_pack = :n where id = :i"),
                  {"n": n, "i": r.id})
    print(f"\n  set units_per_pack on {len(change):,} products")

    # And the shelf figures for those products, which were counted in packs and
    # must now be counted in units — the same conversion the first 990 had.
    moved = c.execute(text("""
        update products set quantity_on_hand = quantity_on_hand * units_per_pack
        where id = any(:ids) and coalesce(quantity_on_hand,0) <> 0
    """), {"ids": [r.id for r, _ in change]}).rowcount
    batches = c.execute(text("""
        update stock_batches b set
            quantity_received = b.quantity_received * p.units_per_pack,
            quantity_remaining = b.quantity_remaining * p.units_per_pack
        from products p
        where p.id = b.product_id and p.id = any(:ids)
    """), {"ids": [r.id for r, _ in change]}).rowcount
    print(f"  converted {moved:,} shelf figures and {batches:,} batch rows to units")
