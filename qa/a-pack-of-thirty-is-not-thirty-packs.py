# -*- coding: utf-8 -*-
"""A product whose pack size is written down but not counted is mispriced.

WHAT THIS FOUND, AND WHY IT IS NOT FIXED HERE

`Product.pack_size` is free text off a supplier's file: "30s", "21s", "10ml".
`Product.units_per_pack` is the integer everything divides by, and it defaults
to 1, meaning "the pack IS the unit". Both are right on their own terms. The
fault is a product that has the first and not the second.

Dispensing prices a line as `per_unit() * quantity`, and `per_unit()` is the
pack price over `units_per_pack`. So on a product labelled "30s" whose
`units_per_pack` is still 1, a script for thirty tablets is charged thirty
times the price of the whole box.

Measured against the demonstration data:

    Amitriptyline        30s   per pack $3.00     30 units billed at $90.00
    Amoxicillin          21s   per pack $4.00     21 units billed at $84.00
    Amoxicillin/Clav     14s   per pack $189.00   21 units billed at $3,969.00
    Amoxicillin 500mg    (21)  per pack $6.30     21 units billed at $6.30

The last row is the same kind of product with the integer filled in, and it is
correct. Two products of identical shape, priced thirty times apart, decided by
whether somebody typed one number.

WHY THIS ONLY REPORTS

Setting `units_per_pack` from `pack_size` changes what patients are charged. If
a pharmacy entered its prices per TABLET while the field said 1, then filling
it in divides every one of those prices by thirty and undercharges by the same
factor it currently overcharges. Which way round it is, is a question about
that pharmacy's data and nobody else can answer it.

So this prints the evidence and proposes nothing. It is run against a pharmacy
to find out what shape its catalogue is in, before anybody decides.

    python qa/a-pack-of-thirty-is-not-thirty-packs.py
"""
from __future__ import annotations

import io
import json
import re
import sys
import urllib.request

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

API = "http://127.0.0.1:8000"

#: "30s", "30 s", "30's", "100 tabs", "1000s". The trailing letter is the
#: supplier's way of saying "of these", and the number in front is the count.
#: Deliberately narrow: "10ml" is a volume and a bottle of it IS one unit, so
#: a pack size ending in a unit of measure is not a count of anything.
COUNTED = re.compile(r"^\s*(\d{1,5})\s*(?:'?s|tabs?|caps?|pcs?|units?)?\s*$", re.I)
MEASURED = re.compile(r"\d\s*(ml|l|g|mg|kg|mcg|iu)\b", re.I)


def looks_counted(pack_size: str) -> int | None:
    """The number of units the label implies, or None if it implies none."""
    said = (pack_size or "").strip()
    if not said or MEASURED.search(said):
        return None
    m = COUNTED.match(said)
    if not m:
        return None
    n = int(m.group(1))
    return n if 1 < n <= 10_000 else None


def token() -> str:
    req = urllib.request.Request(API + "/api/auth/login", method="POST")
    req.add_header("Content-Type", "application/json")
    body = json.dumps({"username": "admin", "password": "admin123"}).encode()
    with urllib.request.urlopen(req, body, timeout=60) as f:
        return json.loads(f.read())["access_token"]


def main() -> int:
    tok = token()
    req = urllib.request.Request(API + "/api/products?limit=5000")
    req.add_header("Authorization", "Bearer " + tok)
    with urllib.request.urlopen(req, timeout=180) as f:
        body = json.loads(f.read())
    rows = body if isinstance(body, list) else (body.get("items") or [])

    disagree, agree, measured, quiet = [], [], 0, 0
    for p in rows:
        implied = looks_counted(p.get("pack_size") or "")
        per = int(p.get("units_per_pack") or 1)
        if implied is None:
            if MEASURED.search((p.get("pack_size") or "")):
                measured += 1
            else:
                quiet += 1
            continue
        (agree if per == implied else disagree).append((p, implied, per))

    print(f"\n  {len(rows)} product(s) read\n")
    print(f"  {len(agree):>5}  say a count and count it")
    print(f"  {measured:>5}  are measured rather than counted "
          f"(a bottle of 10ml is one unit)")
    print(f"  {quiet:>5}  say nothing about a pack")
    print(f"  {len(disagree):>5}  SAY A COUNT AND DO NOT COUNT IT\n")

    if not disagree:
        print("  Nothing to decide: every pack that names a count has it.\n")
        return 0

    worst = sorted(disagree,
                   key=lambda r: -(r[0].get("unit_price") or 0) * r[1])[:12]
    print(f"  {'product':<34} {'label':>7} {'holds':>6} {'per pack':>10} "
          f"{'a full pack is billed at':>26}")
    print("  " + "-" * 92)
    for p, implied, per in worst:
        price = p.get("unit_price") or 0.0
        billed = price * implied / max(per, 1)
        print(f"  {str(p.get('name'))[:33]:<34} {str(p.get('pack_size')):>7} "
              f"{per:>6} {price:>10.2f} {billed:>26,.2f}")
    if len(disagree) > 12:
        print(f"  and {len(disagree) - 12} more")

    print("\n  Each of these prices a whole pack at the pack price times the")
    print("  number in the pack, because the shelf counts units and the")
    print("  catalogue says one unit is one pack.")
    print("\n  NOTHING HAS BEEN CHANGED. Filling these in divides the price of")
    print("  every one of them, so the question is whether this pharmacy's")
    print("  prices are per pack (in which case they are overcharging now) or")
    print("  per tablet (in which case filling them in would undercharge by the")
    print("  same factor). That is a question about their data, and theirs to")
    print("  answer.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"Could not read the catalogue: {e!r}")
        print(f"  The API has to be up at {API}.")
        sys.exit(2)
