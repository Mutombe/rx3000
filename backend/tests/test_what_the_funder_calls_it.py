"""A NAPPI code per funder, and a matcher that would rather say nothing.

A claim is adjudicated on the code. A line with none is rejected and somebody
investigates; a line with the WRONG one is a claim PAID for a medicine the
patient never received, which is fraud with a paper trail leading to the
pharmacy. The two failures are not comparable, and everything here follows from
that: the importer matches timidly, and the counter can always override it.

Against a snapshot of the local database:

  - the code is per (scheme, medicine): two funders, two codes, one box
  - with nothing said, the pharmacy's own NAPPI stands in, and says it is
    standing in
  - with nothing at all, the line is reported as one the funder cannot identify
  - a code typed at the counter is kept against the medicine, for every script
  - clearing it falls back rather than pinning a blank
  - a code that is not digits is refused

And of the importer's matching, which is where the danger is:

  - "ABAC (ABACAVIR SULPHATE) 300MG" does NOT match QUININE SULPHATE 300MG
  - a strength that differs is not the same medicine
  - one ingredient in common is not a match for a combination
  - the same medicine listed twice in the catalogue takes the code twice
  - a published code does not overwrite one somebody typed at the counter

  python tests/test_what_the_funder_calls_it.py
"""
import sys

from snapshot_app import client, execute, sql


def run():
    c = client()
    from app.database import SessionLocal
    from app.importers import cimas_formulary as cimas
    from app.models import MedicalAid, Product, SchemeProductCode
    from app.services import scheme_codes
    from app.tenancy import reset_current_pharmacy, set_current_pharmacy

    aids = c.get("/api/medical-aids").json()
    assert len(aids) >= 2, "need two schemes"
    first, second = aids[0], aids[1]

    stocked = [p for p in c.get("/api/dispensing/products?route=prescription&limit=30").json()
               if (p.get("quantity_on_hand") or 0) >= 1]
    boxed = stocked[0]
    pharmacy_id = sql("select pharmacy_id from products where id = ?", (boxed["id"],))[0][0]
    execute("delete from scheme_product_codes where product_id = ?", (boxed["id"],))
    execute("update products set nappi_code = '' where id = ?", (boxed["id"],))

    # Nothing said by anybody: the funder cannot identify it.
    ask = c.post("/api/scheme-codes", json={"medical_aid_id": first["id"],
                                            "product_ids": [boxed["id"]]}).json()
    assert ask["codes"][0]["origin"] == "none", ask["codes"][0]
    print("ok    with nothing said, the line is one the funder cannot identify")

    # The pharmacy's own NAPPI stands in, and says so.
    execute("update products set nappi_code = '999111' where id = ?", (boxed["id"],))
    ask = c.post("/api/scheme-codes", json={"medical_aid_id": first["id"],
                                            "product_ids": [boxed["id"]]}).json()
    assert ask["codes"][0]["code"] == "999111", ask["codes"][0]
    assert ask["codes"][0]["origin"] == "general", ask["codes"][0]
    print("ok    the pharmacy's own NAPPI stands in, and is labelled as standing in")

    # Two funders, two codes, one box.
    for aid, code in ((first, "37058"), (second, "20797")):
        said = c.put(f"/api/scheme-codes/{aid['id']}/{boxed['id']}", json={"code": code})
        assert said.status_code == 200, said.text
    for aid, code in ((first, "37058"), (second, "20797")):
        got = c.post("/api/scheme-codes", json={"medical_aid_id": aid["id"],
                                                "product_ids": [boxed["id"]]}).json()
        assert got["codes"][0]["code"] == code, (aid["name"], got["codes"][0])
        assert got["codes"][0]["origin"] == "scheme", got["codes"][0]
    print(f"ok    {first['name']} bills 37058 and {second['name']} bills 20797 "
          "for the same box")

    # Kept against the medicine: a second script is already right.
    row = sql("select code, set_by_id from scheme_product_codes where product_id = ? "
              "and medical_aid_id = ?", (boxed["id"], first["id"]))
    assert row and row[0][0] == "37058" and row[0][1], row
    print("ok    it is kept against the medicine, and records who set it")

    letters = c.put(f"/api/scheme-codes/{first['id']}/{boxed['id']}", json={"code": "ABC1"})
    assert letters.status_code == 400 and "digits" in letters.text, letters.text
    print("ok    a code that is not digits is refused")

    cleared = c.put(f"/api/scheme-codes/{first['id']}/{boxed['id']}", json={"code": ""})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["origin"] == "general", cleared.json()
    print("ok    cleared, it falls back to the pharmacy's own rather than pinning a blank")

    # ---- the matcher, where a mistake costs the most ----------------------
    token = set_current_pharmacy(pharmacy_id)
    db = SessionLocal()
    try:
        aid = db.get(MedicalAid, first["id"])
        made = []
        for name, strength in (("Quinine Sulphate 300mg Tabs 60s", ""),
                               ("Abacavir Sulfate 300mg 60s", ""),
                               ("Aripiprazole 10mg Tabs", ""),
                               ("Aripiprazole 15mg Tabs", ""),
                               ("Lamivudine Zidovudine 150/300mg", ""),
                               ("Lamivudine 150mg Tabs", "")):
            code = f"NAP{len(made)}"
            if not sql("select id from products where stock_code = ?", (code,)):
                execute("insert into products (stock_code, name, strength, units_per_pack, "
                        "unit_price, cost_price, quantity_on_hand, vat_rate, pharmacy_id) "
                        "values (?, ?, ?, 1, 1, 0.5, 0, 0, ?)",
                        (code, name, strength, pharmacy_id))
            made.append(code)
        db.expire_all()

        def verdict(description):
            found = cimas.plan(db, [{"code": "11111", "description": description}],
                               aid.id, pharmacy_id)
            if found["matched"]:
                return [p.name for _r, p in found["matched"]]
            if found["ambiguous"]:
                return ["AMBIGUOUS"] + [p.name for p in found["ambiguous"][0][1]]
            return []

        hit = verdict("ABAC (ABACAVIR SULPHATE) 300MG TABLETS")
        assert not any("Quinine" in n for n in hit), hit
        assert any("Abacavir" in n for n in hit), hit
        print(f"ok    ABACAVIR SULPHATE 300MG does not match QUININE SULPHATE 300MG ({hit})")

        hit = verdict("ABILIFY (ARIPIPRAZOLE) 10MG TABLETS")
        assert all("15mg" not in n for n in hit), hit
        print(f"ok    the 10mg code does not land on the 15mg ({hit})")

        hit = verdict("LAMIVUDINE 150MG TABLETS")
        assert not any("Zidovudine" in n for n in hit), hit
        print(f"ok    one ingredient in common is not a combination ({hit})")

        # The same medicine twice in the catalogue takes the code twice.
        if not sql("select id from products where stock_code = 'NAPDUP'"):
            execute("insert into products (stock_code, name, units_per_pack, unit_price, "
                    "cost_price, quantity_on_hand, vat_rate, pharmacy_id) "
                    "values ('NAPDUP', 'Lamivudine 150mg Tabs', 1, 1, 0.5, 0, 0, ?)",
                    (pharmacy_id,))
        db.expire_all()
        found = cimas.plan(db, [{"code": "37058", "description": "LAMIVUDINE 150MG TABLETS"}],
                           aid.id, pharmacy_id)
        assert len(found["matched"]) == 2, [p.name for _r, p in found["matched"]]
        print("ok    one medicine written down twice takes the code twice, not neither")

        # A code somebody typed at the counter is not overwritten by the file.
        typed = sql("select id from products where stock_code = 'NAP5'")[0][0]
        scheme_codes.remember(db, medical_aid_id=aid.id, product_id=typed,
                              code="55555", source="typed at the counter",
                              pharmacy_id=pharmacy_id)
        db.expire_all()
        found = cimas.plan(db, [{"code": "37058", "description": "LAMIVUDINE 150MG TABLETS"}],
                           aid.id, pharmacy_id)
        assert any(p.id == typed for _r, p, _c in found["protected"]), found["protected"]
        print("ok    a published code does not overwrite one typed at the counter")

        forced = cimas.plan(db, [{"code": "37058", "description": "LAMIVUDINE 150MG TABLETS"}],
                            aid.id, pharmacy_id, force=True)
        assert any(p.id == typed for _r, p in forced["matched"]), forced["matched"]
        print("ok    …unless --force says so")
    finally:
        db.close()
        reset_current_pharmacy(token)

    execute("delete from scheme_product_codes where product_id in "
            "(select id from products where stock_code like 'NAP%')")
    execute("delete from products where stock_code like 'NAP%'")
    execute("delete from scheme_product_codes where product_id = ?", (boxed["id"],))


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
