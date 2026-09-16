"""Cimas's own NAPPI codes, read off the formulary they publish.

    python -m app.importers.cimas_formulary --file CIMAS-...-2026.pdf --pharmacy 13
    python -m app.importers.cimas_formulary --file … --pharmacy 13 --apply
    python -m app.importers.cimas_formulary --file … --pharmacy 13 --report out.csv

WHY THIS EXISTS

A funder adjudicates a claim on the NAPPI code, not the name. A line carrying
none is rejected outright, and the pharmacy finds out weeks later in a
remittance — by which time the medicine is gone and so is the patient. Not one
product in this catalogue carries a Cimas code.

Cimas is the one scheme here that publishes its list and keeps it current, so
this is the one list worth importing. The rest are taught at the counter, one
code at a time, by the dispenser holding the box.

MATCHING IS THE WHOLE PROBLEM, AND IT IS DELIBERATELY TIMID

Cimas writes "ABILIFY (ARIPIPRAZOLE) 10MG TABLETS" and the shelf says
"ARIPIPRAZOLE 10MG TABS 30S (ABILIFY)". Same medicine, nothing in common to
sort on. So each side is reduced to what actually identifies a medicine — its
ingredients and its strengths — and the brand names in brackets are kept as
alternative spellings of the same thing rather than thrown away.

A code against the wrong medicine is worse than no code: no code is a rejected
claim that somebody investigates, and a wrong one is a claim PAID for a medicine
the patient never received, which is fraud with a paper trail leading to the
pharmacy. So anything that does not match on ingredient AND strength is left
alone and written to the report for a human, and a Cimas description matching
more than one product in the catalogue is refused rather than guessed between.

WHAT IT WILL NOT OVERWRITE

A code somebody typed at the counter. They were holding the box; the file is a
year old. `--force` says otherwise.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import defaultdict

from ..database import SessionLocal
from ..models import MedicalAid, Product, SchemeProductCode
from ..services import scheme_codes
from ..tenancy import reset_current_pharmacy, set_current_pharmacy, unscoped

SOURCE = "Cimas formulary 2026"

#: Words that describe a pack rather than a medicine. Dropped from both sides
#: before comparing: "TABLETS 30S" and "TABS" are the same medicine.
NOISE = re.compile(
    r"\b(TABLETS?|TABS?|CAPSULES?|CAPS?|CAPLETS?|INJECTIONS?|INJ|VIALS?|AMPOULES?|AMPS?"
    r"|SYRUPS?|SUSPENSIONS?|SOLUTIONS?|CREAMS?|OINTMENTS?|GELS?|LOTIONS?|DROPS?"
    r"|INHALERS?|SPRAYS?|SACHETS?|SUPPOSITOR\w*|PESSAR\w*|POWDERS?|GRANULES?"
    r"|FILM|COATED|SUGAR|ORAL|EYE|EAR|NASAL|TOPICAL|MODIFIED|RELEASE|PROLONGED"
    r"|EFFERVESCENT|DISPERSIBLE|CHEWABLE|FORTE|PLUS|S)\b")

#: A strength: 500MG, 0.4%, 100IU, 5ML, 300/150MG. Commas are decimal points in
#: this document ("16,7 ML"), which is how a European-formatted file reads.
STRENGTH = re.compile(r"\b(\d+(?:[.,]\d+)?(?:/\d+(?:[.,]\d+)?)*)\s*(MG|MCG|G|ML|IU|%|U)\b")


def strengths(text: str) -> frozenset:
    """Every strength in a description, as a set — so order and repetition do
    not matter and "300/150MG" is the same as "300MG/150MG"."""
    out = set()
    for amount, unit in STRENGTH.findall((text or "").upper()):
        for part in amount.replace(",", ".").split("/"):
            try:
                out.add((float(part), unit))
            except ValueError:
                continue
    return frozenset(out)


#: Salts and qualifiers. They are part of an ingredient's full name and they
#: identify nothing on their own: "ABAC (ABACAVIR SULPHATE) 300MG" once matched
#: QUININE SULPHATE 300MG on the strength of the word SULPHATE, which is a claim
#: paid for the wrong medicine — the exact failure this importer exists to avoid.
SALTS = {
    "SULPHATE", "SULFATE", "HYDROCHLORIDE", "HYDROBROMIDE", "HYDROGEN",
    "SODIUM", "POTASSIUM", "CALCIUM", "MAGNESIUM", "ALUMINIUM", "ZINC",
    "MALEATE", "TARTRATE", "CITRATE", "PHOSPHATE", "ACETATE", "FUMARATE",
    "SUCCINATE", "MESYLATE", "BESYLATE", "BROMIDE", "CHLORIDE", "NITRATE",
    "STEARATE", "PALMITATE", "DIPROPIONATE", "VALERATE", "PROPIONATE",
    "FUROATE", "XINAFOATE", "GLUCONATE", "CARBONATE", "OXIDE", "LACTATE",
    "DIHYDRATE", "MONOHYDRATE", "TRIHYDRATE", "ANHYDROUS", "MICRONISED",
    "BASE", "ACID", "SALT", "EXTENDED", "COMBINATION", "PAEDIATRIC",
}

#: The shortest word that is allowed to identify a medicine by itself.
#: "LAMI" and "TENO" are how a formulary abbreviates a combination on one line,
#: and matching a four-letter stump put ACRIPTEGA's code on ZILANEV.
STRONG = 6


def names(text: str) -> tuple[list[str], set[str]]:
    """What a description says this medicine is: its phrases, and its own words.

    "ABILIFY (ARIPIPRAZOLE) 10MG TABLETS" identifies itself twice — a brand and
    an ingredient — and the catalogue may hold either, so both are kept.

    The second half of the answer is the set of words that actually identify
    something: long enough to mean one medicine, and not a salt. Every one of
    them has to appear on a product before it can be called the same medicine,
    which is what stops a combination matching a different combination that
    happens to share one ingredient.
    """
    said = (text or "").upper()
    bracketed = re.findall(r"\(([^)]*)\)", said)
    outside = re.sub(r"\([^)]*\)", " ", said)
    phrases: list[str] = []
    strong: set[str] = set()
    for part in [outside, *bracketed]:
        part = STRENGTH.sub(" ", part)
        part = NOISE.sub(" ", part)
        part = re.sub(r"[^A-Z/]", " ", part)
        # A combination is named by its parts: TENOFOVIR/LAMIVUDINE is two.
        words = [w for w in re.split(r"[\s/]+", part) if len(w) >= 4]
        if words:
            phrases.append(" ".join(words))
            phrases.extend(words)
        strong |= {w for w in words if len(w) >= STRONG and w not in SALTS}
    # Longest first: the full name is a better match than one word of it.
    return sorted(set(phrases), key=len, reverse=True), strong


def narrow(description: str, wanted: list[str], hits: list) -> list:
    """Two candidates that are really one, and one candidate that is really the
    brand named — the only two ways it is safe to pick between them.

    *The same medicine, twice.* This catalogue holds "LAMIVUDINE (3TC) 150MG"
    under two stock codes. Refusing to code either, because there are two, would
    be pedantry: they are the same box and they take the same code.

    *The brand is named.* Cimas writes "ABILIFY (ARIPIPRAZOLE) 10MG" and the
    shelf holds three aripiprazoles, one of which says ABILIFY. That one is what
    the code is for, and the code belongs on it alone — giving it to the generics
    is exactly the wrong-code-paid problem this importer exists to avoid.

    Anything else stays ambiguous and goes to a human.
    """
    squash = lambda s: re.sub(r"[^A-Z0-9]", "", (s or "").upper())
    if len({squash(p.name) for p in hits}) == 1:
        return hits                       # one medicine written down twice

    # Which candidate the description actually names. Scored on the longest
    # name fragments, because "ABILIFY" identifies and "TABLETS" does not.
    def score(product):
        said = squash(product.name)
        return sum(len(name) for name in wanted
                   if len(name) >= STRONG and name not in SALTS
                   and squash(name) and squash(name) in said)

    ranked = sorted(((score(p), p) for p in hits), key=lambda x: -x[0])
    if len(ranked) > 1 and ranked[0][0] > ranked[1][0]:
        return [ranked[0][1]]
    return hits


def read(path: str) -> list[dict]:
    """Every line of the formulary: code, description."""
    import pypdf

    reader = pypdf.PdfReader(path)
    rows: list[dict] = []
    seen: set[str] = set()
    for page in reader.pages:
        for line in (page.extract_text() or "").splitlines():
            line = line.strip()
            # "37058 3TC (LAMIVUDINE) 150MG TABLETS 1 FMED …" — the pack size
            # and source close every row, and the manufacturer sometimes runs
            # into the pack size with no space ("DATLABS1 FMED").
            match = re.match(r"^(\d{3,7})\s+(.*?)\s*(\d+)\s+FMED\b", line)
            if not match:
                continue
            code = match.group(1)
            if code in seen:
                continue
            seen.add(code)
            rows.append({"code": code,
                         "description": re.sub(r"\s+", " ", match.group(2)).strip()})
    if not rows:
        raise SystemExit(f"{path} yielded no formulary lines — is it the Cimas PDF?")
    return rows


def plan(db, rows: list[dict], aid_id: int, pharmacy_id: int,
         force: bool = False) -> dict:
    """Which product each code belongs to, where that can be said safely.

    Scoped to the pharmacy by hand. This runs inside `unscoped()`, so an
    unfiltered query walks every tenant's catalogue and will happily write one
    pharmacy's Cimas code against another pharmacy's product.
    """
    products = [p for p in db.query(Product).filter(Product.pharmacy_id == pharmacy_id).all()
                if (p.name or "").strip()]
    # Indexed by name-fragment so each formulary line looks at a handful of
    # candidates rather than sixteen thousand.
    by_word: dict[str, list] = defaultdict(list)
    detail = {}
    for product in products:
        full = f"{product.name} {product.strength or ''}"
        phrases, strong = names(full)
        detail[product.id] = (phrases, strengths(full), strong,
                              re.sub(r"[^A-Z0-9]", "", full.upper()))
        for name in phrases:
            by_word[name].append(product)

    held = {row.product_id: row for row in
            db.query(SchemeProductCode)
            .filter(SchemeProductCode.medical_aid_id == aid_id).all()}

    matched, ambiguous, unmatched, already, protected = [], [], [], [], []
    # Two formulary lines can name one shelf product — Cimas lists ABAC and
    # ABACAVIR SULPHATE separately and this pharmacy stocks one box. The first
    # code stands and the second is reported rather than silently overwriting
    # it, because "which of these two codes is on file" is not a thing to decide
    # by row order in a PDF.
    doubled: list = []
    spoken: dict = {}
    for row in rows:
        wanted_names, wanted_strong = names(row["description"])
        wanted_strength = strengths(row["description"])
        # Nothing here identifies a medicine on its own — a line of nothing but
        # salts and abbreviations. Left for a human rather than guessed at.
        if not wanted_strong:
            unmatched.append(row)
            continue
        hits = []
        for name in wanted_names:
            for product in by_word.get(name, ()):
                _their_names, their_strength, _their_strong, flat = detail[product.id]
                # EVERY identifying word, not just the one that got us here.
                # A combination that shares one ingredient with another is not
                # the same medicine, and the formulary is full of them.
                if not all(word in flat for word in wanted_strong):
                    continue
                # Strength, exactly, whenever the formulary states one. Not
                # "does not contradict": letting a product that states no
                # strength through put Cimas's 120/60mg abacavir code on KIVEXA,
                # which is 600/300, and its 200mg acetylcysteine code on a 600mg
                # tablet. A code on the 10mg is not a code for the 15mg, and the
                # funder pays on the code.
                if wanted_strength and wanted_strength != their_strength:
                    continue
                hits.append(product)
            if hits:
                break                     # the longest name that matched wins

        hits = list({p.id: p for p in hits}.values())
        if not hits:
            unmatched.append(row)
            continue
        if len(hits) > 1:
            hits = narrow(row["description"], wanted_names, hits)
        squash = lambda s: re.sub(r"[^A-Z0-9]", "", (s or "").upper())
        # More than one, and not the same medicine written down twice: a human
        # decides. `narrow` has already taken the two cases that are safe.
        if len(hits) > 1 and len({squash(p.name) for p in hits}) > 1:
            ambiguous.append((row, hits))
            continue
        for product in hits:
            if product.id in spoken and spoken[product.id] != row["code"]:
                doubled.append((row, product, spoken[product.id]))
                continue
            spoken[product.id] = row["code"]
            existing = held.get(product.id)
            if existing is not None and (existing.code or "").strip() == row["code"]:
                already.append((row, product))
            elif existing is not None and existing.source != SOURCE and not force:
                # Somebody typed this at the counter with the box in their hand.
                protected.append((row, product, existing.code))
            else:
                matched.append((row, product))
    return {"matched": matched, "ambiguous": ambiguous, "unmatched": unmatched,
            "already": already, "protected": protected, "doubled": doubled}


def apply(db, found: dict, aid_id: int, pharmacy_id: int) -> int:
    for row, product in found["matched"]:
        scheme_codes.remember(db, medical_aid_id=aid_id, product_id=product.id,
                              code=row["code"], source=SOURCE,
                              pharmacy_id=getattr(product, "pharmacy_id", None)
                              or pharmacy_id)
    return len(found["matched"])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--file", required=True, help="the Cimas formulary (.pdf)")
    parser.add_argument("--pharmacy", type=int, required=True)
    parser.add_argument("--scheme", default="cimas",
                        help="which scheme on file this list belongs to")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--force", action="store_true",
                        help="also overwrite codes somebody typed at the counter")
    parser.add_argument("--report", help="write every line and its verdict to a CSV")
    args = parser.parse_args(argv)

    rows = read(args.file)
    token = set_current_pharmacy(args.pharmacy)
    db = SessionLocal()
    try:
        aid = (db.query(MedicalAid)
               .filter(MedicalAid.name.ilike(f"%{args.scheme}%")).first())
        if aid is None:
            known = ", ".join(a.name for a in db.query(MedicalAid)
                              .filter(MedicalAid.pharmacy_id == args.pharmacy).all())
            raise SystemExit(f"No scheme here is called '{args.scheme}'. On file: {known}")

        found = plan(db, rows, aid.id, args.pharmacy, force=args.force)
        print(f"\n{len(rows):,} line(s) in the formulary, against {aid.name}"
              + ("" if args.apply else " — nothing written, this is a preview"))
        print(f"{len(found['matched']):,} would take a code")
        print(f"{len(found['already']):,} already carry the one this file gives")
        print(f"{len(found['protected']):,} were typed at the counter and are left alone"
              + (" (--force overwrites)" if not args.force else ""))
        print(f"{len(found['ambiguous']):,} match more than one product and are refused")
        print(f"{len(found['doubled']):,} are a second code for a product already "
              "given one, and are reported rather than applied")
        print(f"{len(found['unmatched']):,} name nothing this pharmacy stocks")

        for row, product in found["matched"][:10]:
            print(f"    {row['code']:<8} {product.name[:34]:<36} {row['description'][:40]}")
        if len(found["matched"]) > 10:
            print(f"    … and {len(found['matched']) - 10:,} more")

        if found["doubled"]:
            print("\n  a second Cimas code for a product that already has one:")
            for row, product, first in found["doubled"][:6]:
                print(f"    {product.name[:30]:<32} has {first}, and "
                      f"{row['code']} also names it ({row['description'][:34]})")

        if found["ambiguous"]:
            print("\n  refused, because more than one product answers to them:")
            for row, hits in found["ambiguous"][:6]:
                print(f"    {row['code']:<8} {row['description'][:38]:<40} -> "
                      + "; ".join(p.name[:22] for p in hits[:3]))

        if args.report:
            with open(args.report, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["nappi", "cimas_description", "verdict", "product"])
                for label, entries in (("matched", found["matched"]),
                                       ("already", found["already"]),
                                       ("protected", [(r, p) for r, p, _c
                                                      in found["protected"]])):
                    for row, product in entries:
                        writer.writerow([row["code"], row["description"], label, product.name])
                for row, hits in found["ambiguous"]:
                    writer.writerow([row["code"], row["description"], "ambiguous",
                                     " | ".join(p.name for p in hits[:4])])
                for row, product, first in found["doubled"]:
                    writer.writerow([row["code"], row["description"],
                                     f"second code (kept {first})", product.name])
                for row in found["unmatched"]:
                    writer.writerow([row["code"], row["description"], "not stocked", ""])
            print(f"\n  every line and its verdict written to {args.report}")

        if args.apply:
            print(f"\n  {apply(db, found, aid.id, args.pharmacy):,} code(s) kept against "
                  f"{aid.name}.")
            print("  The rest are taught at the counter, by whoever is holding the box.")
        return 0
    finally:
        db.close()
        reset_current_pharmacy(token)


if __name__ == "__main__":
    with unscoped():
        sys.exit(main())
