# -*- coding: utf-8 -*-
"""Nothing on the RX5000 claim form is drawn outside the measure.

WHY THIS EXISTS

The first build of this document ran the member's declaration twenty-seven
millimetres off the right of the page, and every right aligned figure a few
millimetres past it, while the code that laid it out was certain every line
fitted. Both were true at once.

Character spacing in PDF is TEXT STATE. It survives BT/ET, so a text object
that does not set it inherits whatever the last one left. This page is built
from letterspaced small caps labels, so every unspaced string drawn after a
label wore that label's spacing: about half a point a character, which on a
hundred and forty character line is most of an inch. `pdfmetrics.stringWidth`
knows the font and nothing about the graphics state, so the wrapper measured
175mm, wrapped happily, and the renderer drew 202mm.

Nothing throws. The PDF opens. The words are simply not on the paper, and the
one that fell off was the sentence the member signs under.

So this reads the FINISHED PDF rather than the layout code, which is the only
place the two can be compared, and asks the one question the layout cannot
answer about itself: is every word between the margins and above the foot.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from app.services import claim_form_rx as rx                # noqa: E402

PT = 25.4 / 72
#: A hair of tolerance, because a right aligned string lands on the margin.
SLACK = 0.6


def a_claim(items: int = 5, long_names: bool = True) -> tuple:
    """A claim with enough on it to push every block down the page."""
    name = ("Co-amoxiclav 625mg dispersible tablets"
            if long_names else "Panado")
    values = {
        "patient_name": "Nomsa Chiwenga-Mutasa", "postal_address":
        "14 Samora Machel Avenue, Eastlea, Harare",
        "medical_scheme": "Premier Service Medical Aid Society",
        "claim_date": "26 Sep 2026", "member_surname": "Chiwenga-Mutasa",
        "member_initials": "NTM", "member_number": "PSMAS-99-174-4421",
        "gross_claimed": "1,284.50", "dependant_suffix": "03",
        "birth_day": "26", "birth_month": "07", "birth_year": "1911",
        "doctor_no": "MP0451234", "pharmacy_no": "PH-00193",
        "prescription_no": "RX260901978",
        "pharmacy_name": "Care Xpress Pharmacy Chinamano Corner",
        "doctor_name": "Dr S. L. Naidoo-Mangwana",
        "gross_total": "1,284.50", "counsel_name": "Chiwenga-Mutasa",
        "counsel_date": "26 Sep 2026",
        "footer_1": "Care Xpress Pharmacy", "footer_2": "Chinamano Corner",
        "footer_3": "Harare", "footer_4": "+263 24 279 4000",
    }
    lines = [{"drug": f"{name} {n + 1}", "price_code": "704112",
              "quantity": "120", "day": "26", "month": "09", "year": "26",
              "charge": "1,284.50"} for n in range(items)]
    said = [f"{name} {n + 1}: Take TWO tablets by mouth three times a day "
            f"after food, and finish the whole course even if you feel better."
            for n in range(items)]
    return values, lines, said


def outside(pdf_bytes: bytes) -> list[str]:
    import io

    import pdfplumber

    bad = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for n, page in enumerate(pdf.pages, 1):
            for w in page.extract_words():
                x0, x1 = w["x0"] * PT, w["x1"] * PT
                top, bottom = w["top"] * PT, w["bottom"] * PT
                where = f'page {n} "{w["text"][:24]}"'
                if x1 > rx.RIGHT + SLACK:
                    bad.append(f"{where} ends at {x1:.1f}mm, past the "
                               f"{rx.RIGHT:.0f}mm margin")
                elif x0 < rx.LEFT - SLACK:
                    bad.append(f"{where} starts at {x0:.1f}mm, before the "
                               f"{rx.LEFT:.0f}mm margin")
                elif bottom > rx.PAGE[1] - 4:
                    bad.append(f"{where} at {top:.1f}mm is off the bottom")
    return bad


def report() -> int:
    faults = []
    for items, label in ((2, "an ordinary script"), (5, "a full script")):
        pdf = rx.render(*a_claim(items))
        if not pdf.startswith(b"%PDF"):
            faults.append(f"{label} did not produce a PDF")
            continue
        faults += [f"{label}: {line}" for line in outside(pdf)]

    # The counselling half is the patient's copy and must never be printed
    # through the imprint: a long script gets a page, not a collision.
    import io

    import pdfplumber
    with pdfplumber.open(io.BytesIO(rx.render(*a_claim(5)))) as pdf:
        for n, page in enumerate(pdf.pages, 1):
            foot = [w for w in page.extract_words()
                    if abs(w["top"] * PT - rx.FOOT) < 3]
            body = [w for w in page.extract_words()
                    if rx.FOOT - 9 < w["top"] * PT < rx.FOOT - 3]
            if foot and body:
                faults.append(f"page {n}: \"{body[0]['text'][:24]}\" is "
                              f"printed into the imprint")

    if not faults:
        print(f"ok  the RX5000 claim form keeps every word between "
              f"{rx.LEFT:.0f} and {rx.RIGHT:.0f}mm and clear of the foot, on "
              f"a two item script and on a five item one")
        return 0
    print(f"\nFAIL  {len(faults)} thing(s) outside the measure\n")
    for line in faults[:30]:
        print("  " + line)
    if len(faults) > 30:
        print(f"  ... and {len(faults) - 30} more")
    print("\n  A word off the measure is a word not on the paper, and the")
    print("  layout cannot see it: character spacing is text state and")
    print("  stringWidth does not read the graphics state.")
    return 1


def plant() -> int:
    """Put the spacing bug back and see this catch it."""
    original = rx.Sheet.text

    def leaky(self, x, y, s, font="Manrope-Regular", size=9.5, colour=None,
              align="left", space=0.0):
        # Exactly the original bug: set the spacing when it is wanted and
        # never clear it, so it leaks into every string that follows.
        if not s:
            return
        s = str(s)
        px, py = x * 2.8346456692913385, (self.h - y) * 2.8346456692913385
        t = self.c.beginText(px, py)
        t.setFont(font, size)
        t.setFillColor(colour if colour is not None else __import__(
            "app.services.brand", fromlist=["x"]).BODY)
        if space:
            t.setCharSpace(space)
        t.textOut(s)
        self.c.drawText(t)

    rx.Sheet.text = leaky
    try:
        bad = outside(rx.render(*a_claim(2)))
    finally:
        rx.Sheet.text = original
    if not bad:
        print("FAIL  the character spacing leak was put back and this said "
              "nothing")
        return 1
    print(f"ok  planted fault caught: {bad[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(plant() if "--plant" in sys.argv else report())
