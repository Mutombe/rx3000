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
class Caption:
    """A word the pre-printed form carries, for when we print the form too."""
    text: str
    x: float
    y: float
    size: float = 6.5
    bold: bool = False


@dataclass(frozen=True)
class Rule:
    """A line or a box on the pre-printed form, in millimetres from the top."""
    x: float
    y: float
    width: float
    height: float = 0.0          # zero is a rule, anything else is a box


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
    #: THE FORM ITSELF, for printing on blank paper.
    #:
    #: Empty for a form we only overlay. Described here rather than in a second
    #: template because the captions have to sit beside the boxes the values
    #: land in, and two descriptions of one sheet drift the first time anybody
    #: moves a field.
    captions: tuple[Caption, ...] = ()
    rules: tuple[Rule, ...] = ()


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
    # ---- the form itself, drawn only when printing on blank paper ----------
    #
    # Deliberately NOT a facsimile. Printing somebody else's stationery is both
    # a copyright question and a losing game: the Paragon original has a
    # tinted ground, a logo and a MedicAlert list on the back that a laser on
    # bond paper cannot reproduce anyway.
    #
    # What it is instead: the same boxes, in the same places, carrying the same
    # captions, so a funder's clerk reading it finds every field where they
    # expect it. The claim is the information, not the artwork.
    captions=(
        Caption("CERTIFIED COPY OF DOCTOR'S PRESCRIPTION / MEDICAL AID "
                "DRUG CLAIM FORM", 22, 7, 9, bold=True),
        Caption("PATIENT'S NAME", 14, 14),
        Caption("POSTAL ADDRESS", 14, 22),
        Caption("MEDICAL SCHEME", 126, 14),
        Caption("DATE", 126, 23),
        Caption("MEMBER'S SURNAME", 14, 34),
        # Above its own box rather than beside it: the surname's field is
        # 62mm wide and reaches 121, so there is no room on that line.
        Caption("MEMBER'S INITS.", 133, 29.5, 5.5),
        Caption("MEMBER'S NUMBER", 14, 40),
        Caption("GROSS AMOUNT CLAIMED", 14, 49),
        Caption("PATIENT DETAILS", 118, 50),
        Caption("SUFFIX", 115, 53, 5),
        Caption("DATE OF BIRTH", 130, 53, 5),
        Caption("MEMBER'S SIGNATURE", 14, 66),
        Caption("DATE", 108, 66),
        Caption("DOCTOR'S No.", 14, 74),
        Caption("PHARMACY No.", 60, 74),
        Caption("PRESCRIPTION No.", 108, 74),
        Caption("NAME OF PHARMACY", 14, 90, 6),
        Caption("NAME OF DOCTOR", 138, 90, 6),
        # the drug table's headings
        Caption("NAME OF DRUG", 24, 100, 5.5, bold=True),
        Caption("PRICE CODE", 82, 100, 5.5, bold=True),
        Caption("QUANT", 100, 100, 5.5, bold=True),
        Caption("DAY", 111, 100, 5.5, bold=True),
        Caption("MTH", 119, 100, 5.5, bold=True),
        Caption("YR", 128, 100, 5.5, bold=True),
        Caption("CHARGE", 136, 100, 5.5, bold=True),
        Caption("R.P.", 154, 100, 5.5, bold=True),
        Caption("GROSS", 118, 135, 7, bold=True),
        Caption("PATIENT COUNSELLING", 70, 162, 11, bold=True),
        Caption("The information below is only a guide. If it does not agree "
                "with instructions given", 48, 169, 6),
        Caption("by your doctor, please follow the doctor's instructions.",
                64, 172.5, 6),
        Caption("NAME", 14, 177),
        Caption("DATE", 134, 177),
    ),
    rules=(
        # the boxes the values go in, so a clerk sees fields rather than text
        Rule(44, 11, 72, 5), Rule(44, 19, 72, 5),
        Rule(148, 11, 56, 5), Rule(148, 20, 56, 5),
        Rule(57, 31, 66, 5), Rule(133, 31, 24, 5),
        Rule(61, 37, 56, 5), Rule(79, 46, 30, 5),
        Rule(115, 52, 11, 5), Rule(127, 52, 11, 5),
        Rule(138, 52, 11, 5), Rule(149, 52, 13, 5),
        Rule(14, 70, 90, 0), Rule(118, 70, 50, 0),      # signature, date
        Rule(28, 75, 36, 5), Rule(74, 75, 36, 5), Rule(127, 75, 36, 5),
        Rule(42, 89, 88, 5), Rule(154, 89, 72, 5),
        Rule(42, 174, 78, 5), Rule(154, 174, 56, 5),
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


#: Blank paper a pharmacy actually has in the office.
PAPERS: dict[str, tuple[float, float]] = {
    "A4": (210.0, 297.0),
    "form": (241.3, 279.4),      # the continuous stationery's own size
}


def render_full(values: dict, lines: list[dict], counselling: list[str], *,
                form: Form = FORM, paper: str = "A4") -> bytes:
    """The whole form, boxes and captions included, on blank paper.

    The other one is an overlay for stationery the pharmacy buys. This is for
    the day the box runs out, for a scheme that takes a printed claim, and for
    anybody who would rather not carry pre-printed stock at all.

    SAME TEMPLATE, SCALED. The field positions are the ones the overlay uses,
    multiplied to fit the paper in the tray — so a value sits in the same place
    relative to its caption whichever way it is printed, and a position fixed
    for one is fixed for both. A4 is narrower and taller than the stationery,
    so the scale is the smaller of the two ratios and the result is centred.

    No calibration here, and that is the point of it: nothing has to line up
    with anything already on the page, because there is nothing on the page.
    """
    w, h = PAPERS.get(paper, PAPERS["A4"])
    scale = min(w / form.width, h / form.height)
    # Centred, so a sheet fed slightly crooked still has margin on every side.
    ox = (w - form.width * scale) / 2
    oy = (h - form.height * scale) / 2

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(w * mm, h * mm))
    c.setTitle(f"{form.name} on {paper}")

    def at(x: float, y: float) -> tuple[float, float]:
        """Template millimetres to points on this paper, top left origin."""
        return ((ox + x * scale) * mm, (h - oy - y * scale) * mm)

    c.setStrokeColorRGB(0.45, 0.45, 0.45)
    c.setLineWidth(0.4)
    for rule in form.rules:
        px, py = at(rule.x, rule.y)
        if rule.height:
            c.rect(px, py - rule.height * scale * mm,
                   rule.width * scale * mm, rule.height * scale * mm)
        else:
            c.line(px, py, px + rule.width * scale * mm, py)

    c.setFillColorRGB(0.1, 0.1, 0.1)
    for cap in form.captions:
        px, py = at(cap.x, cap.y)
        c.setFont("Helvetica-Bold" if cap.bold else "Helvetica",
                  cap.size * scale)
        c.drawString(px, py, cap.text)

    # The drug table as a real grid, which the overlay never draws because the
    # stationery already has one.
    g = form.table
    cols = sorted(g.columns.values(), key=lambda b: b.x)
    left, right = cols[0].x - 1, cols[-1].x + cols[-1].width + 1
    c.setLineWidth(0.4)
    for n in range(g.rows + 1):
        y = g.top - 3.5 + n * g.row_height
        x1, y1 = at(left, y)
        x2, _ = at(right, y)
        c.line(x1, y1, x2, y1)
    top_y = at(left, g.top - 3.5)[1]
    bot_y = at(left, g.top - 3.5 + g.rows * g.row_height)[1]
    for b in cols:
        x1, _ = at(b.x - 1, 0)
        c.line(x1, top_y, x1, bot_y)
    x1, _ = at(right, 0)
    c.line(x1, top_y, x1, bot_y)

    # And the values, through the same placement the overlay uses.
    c.setFillColorRGB(0, 0, 0)

    def value(text, box: Box, extra_y: float = 0.0) -> None:
        if not text:
            return
        text = str(text).strip()
        if not text:
            return
        size = box.size * scale
        while size > 3.5 and c.stringWidth(text, "Courier", size) > box.width * scale * mm:
            size -= 0.25
        c.setFont("Courier", size)
        px, py = at(box.x, box.y + extra_y)
        if box.align == "right":
            px += box.width * scale * mm - c.stringWidth(text, "Courier", size)
        elif box.align == "centre":
            px += (box.width * scale * mm - c.stringWidth(text, "Courier", size)) / 2
        c.drawString(px, py - size * 0.25, text)

    for key, box in form.fields.items():
        value(values.get(key, ""), box)
    for n in range(g.rows):
        row = lines[n] if n < len(lines) else {}
        for key, col in g.columns.items():
            value(row.get(key, ""),
                  Box(x=col.x, y=g.top, width=col.width, size=col.size,
                      align=col.align), n * g.row_height)
    line = form.counselling.columns["line"]
    for n in range(form.counselling.rows):
        if n < len(counselling):
            value(counselling[n],
                  Box(x=line.x, y=form.counselling.top, width=line.width,
                      size=line.size), n * form.counselling.row_height)

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
