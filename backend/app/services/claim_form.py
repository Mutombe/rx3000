"""Printing onto the medical aid claim form a pharmacy buys by the box.

WHAT THIS IS

Zimbabwean pharmacies submit claims on pre-printed continuous stationery:
"CERTIFIED COPY OF DOCTOR'S PRESCRIPTION / MEDICAL AID DRUG CLAIM FORM", with
sprocket holes down both edges, the notes and the MedicAlert list pre-printed
on the back, and a PARAGON mark in the corner. The pharmacy buys the forms; the
software's whole job is to put the right values in the right boxes.

So this is NOT a document we design. `claim_copy.py` is that, and it is a
different thing for a different reader: our own A4 sheet for the shelf and the
inspector. This one is the sheet the funder accepts, and its layout belongs to
whoever printed it.

WHY THE POSITIONS ARE DATA AND NOT CODE

A form is a physical object with a geometry we do not control. The stationery
changes between print runs, printers differ by millimetres, and a tractor
loaded by hand on a Monday is not where it was on Friday. Any arrangement that
bakes coordinates into the drawing code makes each of those a code change.

`FORM` below is therefore a description, read by a renderer that knows nothing
about claims. Two consequences worth having:

  a field moves by editing one number, not by finding it in drawing code;
  a second renderer — ESC/P straight to a dot matrix, which is what tractor
  feed usually means and is far faster than a graphical print — can be written
  against the same description without the layout being done twice.

WHY CALIBRATION IS NOT OPTIONAL

Nothing here can be right out of the box. The numbers below are read off a
scan of a completed form, which is skewed, cropped by the scanner and of
unknown scale; they are a starting point and they say so. What makes it line up
in a particular pharmacy, on a particular printer, is `offset`, which shifts
every field together and is theirs to set once.

`calibration_sheet` exists for exactly that: it prints the boxes this thinks it
is filling, so somebody holds it against a real form, sees that everything is
four millimetres low, and types four. That is a two minute job once, against an
afternoon of trial and error with a stack of forms that cost money.

NOTHING IS PRINTED ON THE BACK. It is pre-printed advice and a tear-off.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field as dc_field
from datetime import date

from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


@dataclass(frozen=True)
class Box:
    """One value's place on the paper.

    `x` and `y` are millimetres from the TOP LEFT of the form, which is how
    somebody holding a ruler against a sheet measures, and not how PDF
    coordinates work — the renderer flips it. Getting that the wrong way round
    is the classic way a form prints upside down from the bottom.
    """
    x: float
    y: float
    #: How much room the value has. Longer text is shrunk to fit rather than
    #: allowed to run into the next box, because a name overrunning into the
    #: scheme column is a claim somebody has to re-key.
    width: float
    size: float = 9.0
    align: str = "left"          # left | right | centre


@dataclass(frozen=True)
class Grid:
    """The drug table: the same columns repeated down a fixed number of rows."""
    top: float                   # the first row's baseline, mm from the top
    row_height: float
    rows: int
    columns: dict[str, Box]      # x/width per column; y is ignored


@dataclass(frozen=True)
class Form:
    name: str
    #: The paper, in millimetres. Continuous stationery is usually 9.5 by 11
    #: inches INCLUDING the sprocket strips, which is what the printer feeds
    #: and therefore what the page has to be.
    width: float
    height: float
    fields: dict[str, Box]
    table: Grid
    #: Free text under the counselling heading, one line per medicine.
    counselling: Grid


#: The standard form, as read off a completed one.
#:
#: EVERY NUMBER HERE IS A STARTING POINT. They were measured from a scan with
#: no scale on it, so they are the shape of the form rather than its exact
#: geometry: the columns are in the right order and the right relative places,
#: and the whole lot will need shifting by a few millimetres against real
#: stationery. That is what `offset` is for, and why nothing here should be
#: nudged in code to fix one pharmacy's printer.
FORM = Form(
    name="RPA drug claim, continuous",
    width=241.3,                 # 9.5 inches
    height=279.4,                # 11 inches
    fields={
        # ---- who it is for -------------------------------------------------
        "patient_name":     Box(x=46, y=14, width=76),
        "postal_address":   Box(x=46, y=22, width=76),
        "medical_scheme":   Box(x=150, y=14, width=52),
        "claim_date":       Box(x=150, y=23, width=52),
        "member_surname":   Box(x=59, y=34, width=62),
        "member_initials":  Box(x=135, y=34, width=20),
        "member_number":    Box(x=63, y=40, width=52),
        "gross_claimed":    Box(x=81, y=49, width=32, align="right"),
        "dependant_suffix": Box(x=117, y=55, width=9, align="centre"),
        "birth_day":        Box(x=129, y=55, width=9, align="centre"),
        "birth_month":      Box(x=140, y=55, width=9, align="centre"),
        "birth_year":       Box(x=151, y=55, width=11, align="centre"),
        # ---- who did it ----------------------------------------------------
        "doctor_no":        Box(x=30, y=78, width=34),
        "pharmacy_no":      Box(x=76, y=78, width=34),
        "prescription_no":  Box(x=129, y=78, width=34),
        "pharmacy_name":    Box(x=44, y=92, width=92),
        "doctor_name":      Box(x=156, y=92, width=70),
        # ---- the totals ----------------------------------------------------
        "gross_total":      Box(x=137, y=135, width=24, align="right"),
        # ---- the counselling half ------------------------------------------
        "counsel_name":     Box(x=44, y=177, width=76),
        "counsel_date":     Box(x=156, y=177, width=52),
        # ---- the pharmacy's own footer -------------------------------------
        "footer_1":         Box(x=14, y=240, width=120, size=8),
        "footer_2":         Box(x=14, y=246, width=120, size=8),
        "footer_3":         Box(x=14, y=252, width=120, size=8),
        "footer_4":         Box(x=14, y=258, width=120, size=8),
    },
    # Five lines on the form, and a sixth medicine needs a second form — which
    # the notes on the back say to attach and submit together.
    table=Grid(
        top=105.0, row_height=5.3, rows=5,
        columns={
            "drug":       Box(x=13, y=0, width=52, size=7),
            "price_code": Box(x=82, y=0, width=16, size=7),
            "quantity":   Box(x=100, y=0, width=9, size=7, align="right"),
            "day":        Box(x=111, y=0, width=7, size=7, align="centre"),
            "month":      Box(x=119, y=0, width=7, size=7, align="centre"),
            "year":       Box(x=127, y=0, width=7, size=7, align="centre"),
            "charge":     Box(x=135, y=0, width=17, size=7, align="right"),
            "repeats":    Box(x=154, y=0, width=7, size=7, align="centre"),
        },
    ),
    counselling=Grid(
        top=183.0, row_height=5.4, rows=6,
        columns={"line": Box(x=14, y=0, width=190, size=8)},
    ),
)


def _fit(c: canvas.Canvas, text: str, box: Box) -> float:
    """The largest size at or below the box's own that still fits its width."""
    size = box.size
    while size > 4.5 and c.stringWidth(text, "Courier", size) > box.width * mm:
        size -= 0.25
    return size


def _put(c: canvas.Canvas, text: str, box: Box, dx: float, dy: float,
         height: float) -> None:
    """One value in one box, measured from the top of the page."""
    if text is None:
        return
    text = str(text).strip()
    if not text:
        return
    size = _fit(c, text, box)
    c.setFont("Courier", size)
    # Millimetres from the top become points from the bottom. The baseline sits
    # a little under the stated y so the text sits ON the ruled line rather
    # than above it, which is where a person writes.
    y = (height - (box.y + dy)) * mm - size * 0.25
    x = (box.x + dx) * mm
    if box.align == "right":
        x += box.width * mm - c.stringWidth(text, "Courier", size)
    elif box.align == "centre":
        x += (box.width * mm - c.stringWidth(text, "Courier", size)) / 2
    c.drawString(x, y, text)


def render(values: dict, lines: list[dict], counselling: list[str], *,
           form: Form = FORM, offset: tuple[float, float] = (0.0, 0.0),
           show_boxes: bool = False) -> bytes:
    """The overlay: the values alone, in their places, on an empty page.

    `offset` is the pharmacy's calibration, in millimetres, applied to
    everything at once: a printer that starts 3mm low and 1mm right is
    (-1, -3). It is deliberately not per field — a tractor feed is off by one
    amount, not by twenty.

    `show_boxes` draws where each value is expected to land, for the
    calibration sheet. Never on a real claim.
    """
    dx, dy = offset
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(form.width * mm, form.height * mm))
    # No compression and no scaling: this has to come out of the printer at
    # exactly the size it was laid out, or every measurement below is a lie.
    c.setTitle(f"{form.name} overlay")

    if show_boxes:
        c.setLineWidth(0.3)
        c.setDash(1, 2)

    for key, box in form.fields.items():
        if show_boxes:
            _outline(c, box, dx, dy, form.height, key)
        else:
            _put(c, values.get(key, ""), box, dx, dy, form.height)

    for n in range(form.table.rows):
        row = lines[n] if n < len(lines) else {}
        dy_row = dy + n * form.table.row_height
        for key, col in form.table.columns.items():
            at = Box(x=col.x, y=form.table.top, width=col.width,
                     size=col.size, align=col.align)
            if show_boxes:
                _outline(c, at, dx, dy_row, form.height,
                         key if n == 0 else "")
            else:
                _put(c, row.get(key, ""), at, dx, dy_row, form.height)

    for n in range(form.counselling.rows):
        said = counselling[n] if n < len(counselling) else ""
        at = Box(x=form.counselling.columns["line"].x, y=form.counselling.top,
                 width=form.counselling.columns["line"].width,
                 size=form.counselling.columns["line"].size)
        if show_boxes and n == 0:
            _outline(c, at, dx, dy, form.height, "counselling")
        elif not show_boxes:
            _put(c, said, at, dx, dy + n * form.counselling.row_height,
                 form.height)

    c.showPage()
    c.save()
    return buffer.getvalue()


def _outline(c: canvas.Canvas, box: Box, dx: float, dy: float,
             height: float, label: str) -> None:
    """Where a value is expected to land, for somebody holding a real form."""
    y = (height - (box.y + dy)) * mm
    c.rect((box.x + dx) * mm, y - 1.2 * mm, box.width * mm, 4.4 * mm)
    if label:
        c.setFont("Helvetica", 4.5)
        c.drawString((box.x + dx) * mm, y + 3.6 * mm, label)


def calibration_sheet(offset: tuple[float, float] = (0.0, 0.0),
                      form: Form = FORM) -> bytes:
    """A sheet to hold against a real form, with a ruler down two edges.

    Printed once, on one form, to answer the only question that matters: how
    far out is this printer. Everything else here is guesswork until somebody
    has done it.
    """
    dx, dy = offset
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(form.width * mm, form.height * mm))
    c.setTitle("Claim form calibration")

    # A ruler along the top and down the left, because "it is about four
    # millimetres low" is a measurement somebody can actually take.
    c.setFont("Helvetica", 4.5)
    c.setLineWidth(0.3)
    for cm in range(0, int(form.width // 10) + 1):
        x = cm * 10 * mm
        c.line(x, form.height * mm, x, (form.height - 4) * mm)
        c.drawString(x + 0.6 * mm, (form.height - 3.4) * mm, f"{cm}")
    for cm in range(0, int(form.height // 10) + 1):
        y = (form.height - cm * 10) * mm
        c.line(0, y, 4 * mm, y)
        c.drawString(0.6 * mm, y - 3.2 * mm, f"{cm}")

    # In the empty band between the drug table and the counselling half, which
    # is the only part of the form with room for a sentence. It was at the top
    # and printed straight through the patient's name box, which on a sheet
    # meant to show where things land is the one mistake it must not make.
    c.setFont("Helvetica", 6)
    c.drawString(14 * mm, (form.height - 152) * mm,
                 f"RX5000 claim form calibration · offset "
                 f"{dx:+.1f}mm across, {dy:+.1f}mm down")
    c.drawString(14 * mm, (form.height - 157) * mm,
                 "Hold this against a blank form. Each box is where a value "
                 "will print, and the rulers are centimetres.")
    c.drawString(14 * mm, (form.height - 162) * mm,
                 "Measure how far out they are and set the offset in Settings. "
                 "Right and down are positive.")
    c.showPage()
    c.save()
    first = buffer.getvalue()

    # The boxes themselves come from the same description the real print uses,
    # so a sheet that lines up means the real one will.
    return _merge(first, render({}, [], [], form=form, offset=offset,
                                show_boxes=True))


def _merge(a: bytes, b: bytes) -> bytes:
    """Two single page PDFs onto one page.

    The ruler and the boxes are drawn by different callers and belong on the
    same sheet; merging is simpler than threading one canvas through both.
    """
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:                                # pragma: no cover
        return b
    one = PdfReader(io.BytesIO(a)).pages[0]
    two = PdfReader(io.BytesIO(b)).pages[0]
    one.merge_page(two)
    out, buffer = PdfWriter(), io.BytesIO()
    out.add_page(one)
    out.write(buffer)
    return buffer.getvalue()


def money(value) -> str:
    """Figures on this form carry no currency mark: the box is already money."""
    try:
        return f"{float(value or 0):.2f}"
    except (TypeError, ValueError):
        return ""


def split_date(when) -> tuple[str, str, str]:
    """Day, month and two digit year, which is how the table asks for it."""
    if not when:
        return "", "", ""
    if isinstance(when, str):
        try:
            when = date.fromisoformat(when[:10])
        except ValueError:
            return "", "", ""
    return f"{when.day:02d}", f"{when.month:02d}", f"{when.year % 100:02d}"
