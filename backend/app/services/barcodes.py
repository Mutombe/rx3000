"""Turning whatever the scanner emitted into something we can look up.

A scan is not a product code. It is a string that arrived from a device, and
between the two sit several failures that are all common enough to have bitten
every pharmacy system that ignored them:

* **The same medicine has more than one barcode.** The originator's pack, the
  generic, and the parallel import each carry their own EAN, and a pharmacy that
  buys from two wholesalers will hold both on the shelf at once. One `barcode`
  column on the product silently makes the second pack unscannable.

* **A GTIN has four widths.** UPC-A (12), EAN-13, ITF-14 on the outer, and the
  GS1 databar. They are the *same* article number with different amounts of
  left-hand zero padding. Compare them as strings and a pack scans at goods
  receipt but not at the till.

* **Spreadsheets eat leading zeros.** Supplier price files arrive as CSV, Excel
  reads `0761234567890` as a number, and the code that reaches our database is
  missing its first digit. We cannot fix the supplier, so we match with the zero
  restored as well as without.

* **The interesting packs are not numbers at all.** Pharmaceutical secondary
  packaging carries a GS1 DataMatrix, and inside it are the batch number and the
  expiry date. A goods receipt that reads them off the pack is the difference
  between typing three fields per line and typing none, and — because the batch
  and expiry are now transcribed by machine rather than by a tired person at the
  end of a delivery — it is also the difference between a recall you can action
  and one you cannot.

Everything here is pure. Nothing touches the database, so the parsing can be
tested on strings alone, and the resolver above it stays a single small query.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

# Group Separator. GS1 uses it to terminate a variable-length element when the
# next one follows, and a keyboard-wedge scanner will happily type it at us.
GS = "\x1d"

# Element identifiers we care about, with the fixed length of their value where
# GS1 defines one. A fixed-length element needs no separator after it, which is
# the whole reason this table has to exist rather than splitting on GS.
FIXED_LENGTH = {
    "00": 18,  # SSCC, on the shipping container
    "01": 14,  # GTIN — the article number
    "02": 14,  # GTIN of the contained trade items
    "11": 6,   # production date
    "15": 6,   # best before
    "17": 6,   # expiry            YYMMDD
}
# Variable-length elements run to the next GS, or to the end of the string.
VARIABLE = {
    "10": "batch",    # batch / lot
    "21": "serial",
    "30": "count",
    "37": "count",
    "710": "reimbursement",  # national healthcare reimbursement number
    "711": "reimbursement",
    "712": "reimbursement",
    "713": "reimbursement",
}


@dataclass
class Scan:
    """What a scan turned out to mean.

    `keys` is the point of the whole module: the list of strings worth trying
    against the database, most specific first. The caller does one `IN` query
    with it rather than a chain of fallbacks.
    """
    raw: str
    code: str = ""                    # the article number, normalised
    symbology: str = "plain"          # plain | gs1 | ean13 | upc | itf14
    batch: str = ""
    expiry: date | None = None
    serial: str = ""
    keys: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def carries_batch(self) -> bool:
        """Whether this scan can fill in a goods-receipt line by itself."""
        return bool(self.batch or self.expiry)


def _check_digit(digits: str) -> str:
    """GS1 mod-10. Weights alternate 3 and 1 from the right of the payload."""
    total = 0
    for i, ch in enumerate(reversed(digits)):
        total += int(ch) * (3 if i % 2 == 0 else 1)
    return str((10 - total % 10) % 10)


def valid_gtin(code: str) -> bool:
    """True if the check digit agrees. Used to *classify*, never to reject.

    A code that fails this is still looked up. Pharmacies print their own labels
    for repacks and compounded items, and those are frequently not valid GTINs;
    refusing to scan them because a checksum disagrees would break a workflow
    that works fine today.
    """
    if not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return False
    return _check_digit(code[:-1]) == code[-1]


def gtin_variants(code: str) -> list[str]:
    """Every width the same article number could have been stored as.

    A GTIN is defined right-aligned in a 14-digit field, so `0000761234567890`,
    `761234567890` and `07612345678901` can all be the same product depending on
    who typed it in. Normalising to 14 and then re-expanding covers the lot.
    """
    if not code.isdigit():
        return []
    padded = code.rjust(14, "0")
    out = [code, padded.lstrip("0"), padded]
    for width in (8, 12, 13, 14):
        if len(padded) >= width:
            trimmed = padded[-width:]
            # Only a genuine widening — dropping a significant digit would be a
            # different article, not the same one written differently.
            if trimmed.rjust(14, "0") == padded:
                out.append(trimmed)
    # Excel opened the supplier's CSV and ate the leading zero.
    if len(code) in (11, 12) and code.isdigit():
        out.append("0" + code)
    seen, unique = set(), []
    for c in out:
        if c and c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


def _gs1_date(value: str) -> date | None:
    """YYMMDD, where DD may be `00` meaning 'the end of that month'.

    The century is inferred: GS1 says a year 51 or more years ahead is past, and
    for medicine expiry dates that rule is never wrong in practice — nothing on
    the shelf expires in 1998 and nothing expires in 2081.
    """
    if len(value) != 6 or not value.isdigit():
        return None
    yy, mm, dd = int(value[:2]), int(value[2:4]), int(value[4:])
    if not 1 <= mm <= 12:
        return None
    year = 2000 + yy
    if year > date.today().year + 50:
        year -= 100
    if dd == 0:
        # Last day of the month. The pack means "usable through this month".
        nxt = date(year + (mm == 12), (mm % 12) + 1, 1)
        return date.fromordinal(nxt.toordinal() - 1)
    try:
        return date(year, mm, dd)
    except ValueError:
        return None


def parse_gs1(raw: str) -> dict:
    """Pull the element strings out of a GS1-128 or DataMatrix payload.

    Returns `{}` when the string is not GS1, so the caller can fall through to
    treating it as a plain code without asking twice.
    """
    s = raw.strip()
    # Some scanners emit the FNC1 as a literal `]d2`/`]C1` AIM identifier, some
    # as GS, some as bracketed AIs for human readability. Accept all three.
    s = re.sub(r"^\][A-Za-z]\d?", "", s)
    bracketed = "(" in s and ")" in s
    if bracketed:
        # Human-readable form: `(10)ABC(21)XYZ`. Swap each bracket for a
        # separator rather than deleting it — a variable-length element needs
        # something to terminate it, or the batch swallows the serial.
        s = re.sub(r"\((\d{2,4})\)", GS + r"\1", s).lstrip(GS)

    if not (s.startswith(("01", "00", "17", "10", "21", "11")) or GS in s or bracketed):
        return {}

    out: dict = {}
    i = 0
    while i < len(s):
        if s[i] == GS:
            i += 1
            continue
        ai = None
        for width in (2, 3, 4):
            candidate = s[i:i + width]
            if candidate in FIXED_LENGTH or candidate in VARIABLE:
                ai = candidate
                break
        if ai is None:
            # Unrecognised element. We cannot know its length, so we cannot
            # safely keep reading — stop and use what we have.
            out.setdefault("_partial", True)
            break
        i += len(ai)
        if ai in FIXED_LENGTH:
            value, i = s[i:i + FIXED_LENGTH[ai]], i + FIXED_LENGTH[ai]
        else:
            end = s.find(GS, i)
            end = len(s) if end == -1 else end
            value, i = s[i:end], end
        if ai in ("01", "02"):
            out["gtin"] = value
        elif ai == "17":
            out["expiry"] = _gs1_date(value)
        elif ai in ("11", "15"):
            out.setdefault("expiry", _gs1_date(value))
        elif ai == "10":
            out["batch"] = value
        elif ai == "21":
            out["serial"] = value
        elif ai == "00":
            out["sscc"] = value
    return out


def read(raw: str) -> Scan:
    """The single entry point. Give it whatever arrived; get back what to query."""
    scan = Scan(raw=raw or "")
    text = (raw or "").strip()
    # A wedge scanner may append its terminator, and a phone camera may hand us
    # a payload with stray whitespace from the decoder.
    text = text.strip("\r\n\t ")
    if not text:
        return scan

    gs1 = parse_gs1(text)
    if gs1.get("gtin"):
        scan.symbology = "gs1"
        scan.code = gs1["gtin"]
        scan.batch = (gs1.get("batch") or "").strip()
        scan.expiry = gs1.get("expiry")
        scan.serial = (gs1.get("serial") or "").strip()
        if gs1.get("_partial"):
            scan.warnings.append(
                "Part of this code used an element we do not read. "
                "The product and batch below are what we could make out."
            )
        scan.keys = gtin_variants(scan.code)
        return scan

    if gs1.get("sscc"):
        # A pallet label, not a product. Say so rather than returning nothing:
        # the difference between "wrong label" and "unknown product" is the
        # difference between a two-second fix and a support call.
        scan.symbology = "gs1"
        scan.warnings.append(
            "That is a shipping-container label, not a product barcode. "
            "Scan the barcode on the item itself."
        )
        return scan

    scan.code = text
    if text.isdigit():
        scan.symbology = {8: "ean8", 12: "upc", 13: "ean13", 14: "itf14"}.get(len(text), "plain")
        scan.keys = gtin_variants(text)
        if len(text) in (8, 12, 13, 14) and not valid_gtin(text):
            # Not fatal — own-label codes fail this legitimately — but worth
            # saying when the lookup also comes back empty.
            scan.warnings.append("The check digit on this code does not add up; it may have misread.")
    else:
        # A NAPPI code, an own-label SKU, or someone typing a product name.
        scan.keys = [text, text.upper()]
    return scan
