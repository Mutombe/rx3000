# -*- coding: utf-8 -*-
"""Every value on the claim form is on the paper, and nothing writes over itself.

WHAT THIS IS FOR

The medical aid claim form is pre-printed stationery a pharmacy buys by the
box, and the software prints only the values into its boxes. Two things can go
wrong that nothing else would notice:

  a value lands OFF the paper, because somebody changed a coordinate or the
  calibration offset is large, and the claim is submitted with a blank where
  the member number should be;

  two values land ON each other, because two boxes overlap, and the funder
  gets one figure printed over another.

Neither throws. Both produce a PDF that looks fine in a viewer until it is held
against a real form, by which time the form is spoiled and forms cost money.

WHAT THIS CANNOT CHECK

Whether the positions are RIGHT — whether the member number lands in the member
number box. Nothing in software can know that: the geometry belongs to a
printed sheet nobody here has. That is what the calibration sheet is for, and
why the template says its numbers are a starting point.

So this checks the two things that are knowable: everything is on the page, and
nothing collides. It is the difference between "we cannot verify the layout" and
"we cannot verify anything".
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
os.chdir(ROOT / "backend")

from app.services import claim_form                   # noqa: E402

#: How far a pharmacy might reasonably have to shift everything, in mm. A
#: printer out by more than this is loaded wrong, not calibrated wrong.
OFFSETS = [(0, 0), (6, 6), (-6, -6), (10, 0), (0, 10)]


def boxes(form: claim_form.Form) -> list[tuple[str, claim_form.Box]]:
    """Every place a value can land, the table's rows included."""
    out = [(k, b) for k, b in form.fields.items()]
    for n in range(form.table.rows):
        for key, col in form.table.columns.items():
            out.append((f"{key}[{n}]", claim_form.Box(
                x=col.x, y=form.table.top + n * form.table.row_height,
                width=col.width, size=col.size, align=col.align)))
    line = form.counselling.columns["line"]
    for n in range(form.counselling.rows):
        out.append((f"counselling[{n}]", claim_form.Box(
            x=line.x, y=form.counselling.top + n * form.counselling.row_height,
            width=line.width, size=line.size)))
    return out


def off_the_paper(form, dx, dy) -> list[str]:
    bad = []
    for name, b in boxes(form):
        left, right = b.x + dx, b.x + dx + b.width
        top, bottom = b.y + dy, b.y + dy + b.size * 0.4
        if left < 0 or right > form.width or top < 0 or bottom > form.height:
            bad.append(f"{name} at {left:.0f},{top:.0f} to "
                       f"{right:.0f},{bottom:.0f} is outside "
                       f"{form.width:.0f}x{form.height:.0f}")
    return bad


def on_top_of_each_other(form) -> list[str]:
    """Two boxes sharing paper. Measured without the offset, which moves all."""
    bad, seen = [], boxes(form)
    for i, (an, a) in enumerate(seen):
        for bn, b in seen[i + 1:]:
            # A row of the table and the row under it are a line apart; only an
            # actual overlap of the ink counts, so the height is the type.
            ah, bh = a.size * 0.4, b.size * 0.4
            if (a.x < b.x + b.width and b.x < a.x + a.width
                    and a.y < b.y + bh and b.y < a.y + ah):
                bad.append(f"{an} and {bn} overlap")
    return bad


def renders(form) -> list[str]:
    """It produces a PDF of the right paper size, with something on it."""
    bad = []
    values = {k: "X" * 8 for k in form.fields}
    lines = [{k: "9" for k in form.table.columns} for _ in range(form.table.rows)]
    said = ["A medicine: take one twice a day"] * form.counselling.rows
    pdf = claim_form.render(values, lines, said)
    if not pdf.startswith(b"%PDF"):
        bad.append("render did not produce a PDF")
        return bad
    if len(pdf) < 900:
        bad.append(f"the PDF is {len(pdf)} bytes, which is an empty page")
    try:
        from pypdf import PdfReader
        page = PdfReader(io.BytesIO(pdf)).pages[0]
        w = float(page.mediabox.width) / 72 * 25.4
        h = float(page.mediabox.height) / 72 * 25.4
        if abs(w - form.width) > 1 or abs(h - form.height) > 1:
            bad.append(f"the page is {w:.0f}x{h:.0f}mm, not "
                       f"{form.width:.0f}x{form.height:.0f}")
    except ImportError:                                # pragma: no cover
        pass
    if not claim_form.calibration_sheet().startswith(b"%PDF"):
        bad.append("the calibration sheet did not produce a PDF")
    return bad


def report() -> int:
    form = claim_form.FORM
    faults = renders(form) + on_top_of_each_other(form)
    for dx, dy in OFFSETS:
        for line in off_the_paper(form, dx, dy):
            faults.append(f"offset {dx:+},{dy:+}: {line}")
    if not faults:
        print(f"ok  {len(boxes(form))} value positions on {form.name}: every "
              f"one on the paper at offsets up to 10mm, none on top of "
              f"another, and the page comes out "
              f"{form.width:.0f}x{form.height:.0f}mm")
        return 0
    print(f"\nFAIL  {len(faults)} thing(s) wrong with the claim form\n")
    for line in faults[:40]:
        print("  " + line)
    if len(faults) > 40:
        print(f"  ... and {len(faults) - 40} more")
    print("\n  A value off the paper is a blank box on a submitted claim, and")
    print("  two on each other is one figure printed over another. Neither")
    print("  throws, and both spoil a form that cost money.")
    return 1


def plant() -> int:
    """Move one box off the paper and see this say so."""
    import dataclasses
    form = claim_form.FORM
    moved = dataclasses.replace(
        form, fields={**form.fields,
                      "member_number": claim_form.Box(
                          x=form.width + 5, y=20, width=40)})
    bad = off_the_paper(moved, 0, 0)
    if not bad:
        print("FAIL  a value was put past the edge of the paper and this said "
              "nothing")
        return 1
    print(f"ok  planted fault caught: {bad[0]}")
    return 0


if __name__ == "__main__":
    sys.exit(plant() if "--plant" in sys.argv else report())
