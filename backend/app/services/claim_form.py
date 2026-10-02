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
    # MEASURED OFF THE SCAN, not guessed. Two measurements fix the scale and
    # everything else is read against them.
    #
    # ACROSS: the scan carries sprocket holes down both edges at the standard
    # half inch pitch. 84.75px between hole centres is 12.7mm, so the scan is
    # 6.673 px/mm and 198.7mm across, and the form is eight inches wide. It
    # said 241.3 here once, nine and a half inches, because that is the
    # commonest continuous width and nothing had measured it. Every x was
    # nineteen per cent too far across, and a scale error is the one thing the
    # calibration offset CANNOT absorb: an offset shifts, it does not scale.
    #
    # DOWN: the drug table's own rules, read in the line number column where
    # the ink is darkest, land at 103.3, 109.5, 116.1, 122.9, 129.3 and 135.2.
    # Five rows of 6.37mm, not the 5.13 this carried, so lines three to five
    # were climbing out of their boxes a millimetre at a time.
    width=203.2,                 # 8 inches, measured off the sprockets
    height=279.4,                # 11 inches, the standard length
    fields={
        # ---- who it is for -------------------------------------------------
        "patient_name":     Box(x=38.0, y=14.3, width=70.0),
        "postal_address":   Box(x=38.0, y=25.3, width=70.0),
        "medical_scheme":   Box(x=124.9, y=14.3, width=52.0),
        "claim_date":       Box(x=131.1, y=22.8, width=46.0),
        "member_surname":   Box(x=49.2, y=33.8, width=35.0),
        "member_initials":  Box(x=111.4, y=33.5, width=16.0),
        "member_number":    Box(x=54.4, y=42.4, width=28.0),
        "gross_claimed":    Box(x=66.0, y=50.5, width=22.5, align="right"),
        "dependant_suffix": Box(x=98.3, y=57.7, width=6.0, align="centre"),
        "birth_day":        Box(x=107.3, y=59.8, width=5.7, align="centre"),
        "birth_month":      Box(x=114.0, y=59.8, width=7.3, align="centre"),
        "birth_year":       Box(x=122.3, y=59.8, width=6.2, align="centre"),
        # ---- who did it ----------------------------------------------------
        "doctor_no":        Box(x=24.0, y=83.6, width=21.5),
        "pharmacy_no":      Box(x=61.3, y=83.6, width=21.5),
        "prescription_no":  Box(x=107.3, y=83.6, width=24.5),
        # Clear of its own caption. The original sets NAME OF / PHARMACY hard
        # against the value and prints PHARMACYCARE XPRESS PHARMACY, which is
        # the kind of thing a clerk reads twice.
        "pharmacy_name":    Box(x=35.4, y=94.9, width=68.5),
        "doctor_name":      Box(x=130.0, y=94.9, width=55.0),
        # ---- the totals ----------------------------------------------------
        # In the CHARGE column, on the line under the table, where the form
        # prints GROSS and a dollar sign.
        "gross_total":      Box(x=113.0, y=140.0, width=13.2, align="right"),
        # ---- the counselling half ------------------------------------------
        "counsel_name":     Box(x=36.5, y=180.8, width=60.0),
        "counsel_date":     Box(x=137.0, y=180.8, width=40.0),
        # ---- the pharmacy's own footer -------------------------------------
        # The bottom third of the form is blank: nothing of the funder's is
        # printed below the counselling lines, so that space is the pharmacy's.
        "footer_1":         Box(x=11.5, y=240.0, width=98.8, size=8),
        "footer_2":         Box(x=11.5, y=244.5, width=98.8, size=8),
        "footer_3":         Box(x=11.5, y=249.0, width=98.8, size=8),
        "footer_4":         Box(x=11.5, y=253.5, width=98.8, size=8),
    },
    # Five lines on the form, and a sixth medicine needs a second form, which
    # the notes say to attach and submit together.
    #
    # The columns are the gaps between the measured vertical rules, which fall
    # at 13.5, 55.7, 60.8, 66.0, 83.5, 93.7, 99.8, 106.0, 112.0, 127.2 and
    # 131.2mm, each inset a millimetre so a value never touches a rule.
    #
    # LINE and P/R are the form's own: the line number is pre-printed on the
    # stationery and the repeat marker is written by hand, so we fill neither.
    # They are columns here because they are columns on the paper, and leaving
    # them out would run the drug name across both of them.
    table=Grid(
        top=107.8, row_height=6.37, rows=5,
        columns={
            "drug":       Box(x=14.5, y=0.0, width=40.2, size=8),
            "line_no":    Box(x=56.7, y=0.0, width=3.1, size=6, align="centre"),
            "p_r":        Box(x=61.8, y=0.0, width=3.2, size=6, align="centre"),
            "price_code": Box(x=67.0, y=0.0, width=15.5, size=8),
            "quantity":   Box(x=84.5, y=0.0, width=8.2, size=8, align="right"),
            "day":        Box(x=94.7, y=0.0, width=4.1, size=8, align="centre"),
            "month":      Box(x=100.8, y=0.0, width=4.2, size=8, align="centre"),
            "year":       Box(x=107.0, y=0.0, width=4.0, size=8, align="centre"),
            "charge":     Box(x=113.0, y=0.0, width=13.2, size=8, align="right"),
            "repeats":    Box(x=128.2, y=0.0, width=2.0, size=6, align="centre"),
        },
    ),
    # Eight lines of advice under the rule, at the size the form's own filled
    # example was typed at: this is the half the patient reads at home.
    counselling=Grid(
        top=188.0, row_height=5.6, rows=8,
        columns={"line": Box(x=13.5, y=0.0, width=160.0, size=11)},
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
    #
    # The captions the original sets on two lines are set on two lines here,
    # which is not cosmetic: MEDICAL SCHEME on one line is twenty millimetres
    # long and runs into the box its own value lands in.
    captions=(
        Caption("CERTIFIED COPY OF DOCTOR'S PRESCRIPTION / MEDICAL AID "
                "DRUG CLAIM FORM", 18.2, 6.9, 10.5, bold=True),
        Caption("PATIENT'S", 21.7, 12.3),
        Caption("NAME", 21.7, 16.6),
        Caption("POSTAL", 21.7, 23.2),
        Caption("ADDRESS", 21.7, 26.6),
        Caption("MEDICAL", 110.6, 12.3),
        Caption("SCHEME", 110.6, 16.6),
        Caption("DATE", 123.0, 23.6),
        Caption("MEMBER'S SURNAME", 17.4, 35.0),
        Caption("MEMBER'S INITS.", 86.8, 35.0),
        Caption("MEMBER'S NUMBER", 21.3, 42.4),
        Caption("GROSS AMOUNT CLAIMED", 17.9, 50.5),
        Caption("$", 63.5, 50.5),
        # The funder's own side of the sheet. We never write in these, and a
        # claim printed without them is missing the boxes a clerk date stamps.
        Caption("CLAIM NUMBER", 149.2, 34.7, 7),
        Caption("DATE STAMP", 137.3, 45.9, 7),
        Caption("DATE STAMP", 164.7, 45.9, 7),
        Caption("DELAY", 141.5, 63.0, 5),
        Caption("P.M.", 151.5, 63.0, 5),
        Caption("B/P", 162.0, 62.0, 4.5),
        Caption("O/R", 162.0, 64.4, 4.5),
        Caption("STAFF", 171.0, 63.0, 5),
        Caption("PATIENT DETAILS", 100.6, 51.0, 7),
        Caption("SUFFIX", 98.3, 54.3, 5),
        Caption("DATE OF BIRTH", 107.3, 54.3, 5),
        # The member's declaration, which is what makes the signature mean
        # something. Six lines on the original and six here.
        Caption("I confirm that the details given above are correct and that "
                "this claim", 16.3, 55.4, 5),
        Caption("is lodged against my medical aid society in the utmost good "
                "faith.", 16.3, 57.2, 5),
        Caption("I confirm that the amount claimed herein is not claimable "
                "from", 16.3, 59.0, 5),
        Caption("another source and I understand that no awards are payable "
                "in", 16.3, 60.8, 5),
        Caption("respect of this claim until such time as my medical aid "
                "society has", 16.3, 62.6, 5),
        Caption("received contributions in respect of the stated period of "
                "treatment.", 16.3, 64.4, 5),
        Caption("MEMBER'S SIGNATURE", 21.3, 72.0),
        Caption("DATE", 102.1, 72.0),
        Caption("DOCTOR'S No.", 26.7, 77.9, 6),
        Caption("PHARMACY No.", 64.4, 77.9, 6),
        Caption("PRESCRIPTION No.", 107.5, 77.9, 6),
        Caption("B/P", 153.5, 76.5, 4.5),
        Caption("O/R", 153.5, 78.8, 4.5),
        Caption("P.M.", 163.0, 77.9, 5),
        Caption("STAFF", 171.5, 77.9, 5),
        Caption("NAME OF", 20.3, 92.0, 6),
        Caption("PHARMACY", 20.3, 95.2, 6),
        Caption("NAME OF", 118.4, 92.0, 6),
        Caption("DOCTOR", 118.4, 95.2, 6),
        # the drug table's headings, each centred in its own column
        Caption("NAME OF DRUG", 27.4, 102.2, 5.5, bold=True),
        Caption("LINE", 55.9, 102.2, 5.5, bold=True),
        Caption("P/R", 61.6, 102.2, 5.5, bold=True),
        Caption("PRICE CODE", 68.8, 102.2, 5.5, bold=True),
        Caption("QUANT.", 85.0, 102.2, 5.5, bold=True),
        Caption("DAY", 95.0, 102.2, 5.5, bold=True),
        Caption("MTH", 101.1, 102.2, 5.5, bold=True),
        Caption("YR", 107.8, 102.2, 5.5, bold=True),
        Caption("CHARGE", 116.0, 102.2, 5.5, bold=True),
        Caption("R.P.", 127.3, 102.2, 4.5, bold=True),
        # and the funder's columns beside them, which carry the SHORTFALL the
        # till later asks the patient for.
        Caption("AWARD", 138.5, 102.2, 5.5, bold=True),
        Caption("SHORTFALL", 151.9, 102.2, 5.5, bold=True),
        Caption("REASON", 166.8, 102.2, 5.5, bold=True),
        Caption("B/P", 175.9, 100.8, 4.5, bold=True),
        Caption("O/R", 175.9, 102.9, 4.5, bold=True),
        Caption("STAFF", 181.5, 102.2, 4.5, bold=True),
        Caption("GROSS", 94.0, 140.0, 9, bold=True),
        Caption("$", 109.8, 140.0, 8, bold=True),
        # The notes, in the band under the table that was empty here and is
        # not empty on the form. Note one says BLUE on the original, meaning
        # its tinted ground; on bond paper there is no blue, so it says what
        # is true of this sheet instead.
        Caption("NOTES", 15.4, 137.4, 5, bold=True),
        Caption("1) ANY SECTION NOT COMPLETED BY THE COMPUTER MUST BE "
                "COMPLETED BY", 15.4, 139.4, 5),
        Caption("   MEMBER/PATIENT. ALL OTHER SECTIONS ARE FOR OFFICIAL USE "
                "ONLY.", 15.4, 141.4, 5),
        Caption("2) IF ANOTHER CLAIM FORM IS ATTACHED TO THIS FORM, ENSURE "
                "THAT IT IS SUBMITTED TOGETHER WITH THIS FORM.",
                15.4, 143.4, 5),
        Caption("3) PLEASE ADHERE TO ANY OTHER SPECIAL CONDITIONS OF YOUR "
                "MEDICAL AID SOCIETY.", 15.4, 145.4, 5),
        Caption("4) CERTAIN SECTIONS OF THE FORM MAY NOT BE REQUIRED BY YOUR "
                "MEDICAL AID SOCIETY AND WILL REMAIN BLANK.",
                15.4, 147.4, 5),
        Caption("5) RETAIN THIS FORM FOR SUBMISSION TO THE DEPARTMENT OF "
                "TAXES IF YOU ARE NOT COVERED BY A DRUG BENEFIT SCHEME.",
                15.4, 149.4, 5),
        Caption("6) DO NOT LOSE THIS FORM AS A FEE MAY BE CHARGED FOR A COPY.",
                15.4, 151.4, 5),
        Caption("7) PLEASE CHECK ALL DETAILS CAREFULLY. IF ANY INFORMATION "
                "PRINTED BY THE COMPUTER IS INCORRECT OR HAS BEEN OMITTED, "
                "PLEASE NOTIFY US.", 15.4, 153.4, 5),
        Caption("REPEATS LEFT ON PRESCRIPTION", 135.1, 143.1, 7, bold=True),
        Caption("PATIENT COUNSELLING", 66.6, 161.9, 15, bold=True),
        Caption("THE INFORMATION GIVEN BELOW IS ONLY A GUIDE. IF IT DOES NOT",
                40.5, 166.1, 9),
        Caption("AGREE WITH INSTRUCTIONS GIVEN BY YOUR DOCTOR, PLEASE",
                57.3, 170.5, 9),
        Caption("FOLLOW THE DOCTOR'S INSTRUCTIONS.", 64.5, 174.8, 9),
        Caption("NAME", 26.5, 181.7, 8),
        Caption("DATE", 127.3, 181.7, 8),
    ),
    rules=(
        # the boxes the values go in, so a clerk sees fields rather than text
        Rule(36.0, 10.4, 72.0, 6.2),      # patient's name
        Rule(36.0, 20.8, 72.0, 6.2),      # postal address
        Rule(13.5, 29.8, 174.4, 0),       # the band under the patient
        Rule(16.3, 39.1, 67.0, 6.2),      # member's number
        Rule(16.3, 47.4, 73.2, 6.2),      # gross amount claimed
        # Under their captions, not through them: the box top was at 53.0 and
        # SUFFIX and DATE OF BIRTH sit on that line.
        Rule(97.8, 55.0, 6.9, 7.0),       # suffix
        Rule(106.8, 55.0, 6.7, 7.0),      # day of birth
        Rule(113.5, 55.0, 8.3, 7.0),      # month
        Rule(121.8, 55.0, 7.2, 7.0),      # year
        # the funder's own side
        Rule(131.0, 30.7, 54.8, 7.4),     # claim number
        Rule(131.0, 40.7, 27.9, 18.6),    # date stamp
        Rule(158.9, 40.7, 26.9, 18.6),    # date stamp
        Rule(140.3, 60.0, 9.3, 8.8), Rule(149.6, 60.0, 9.3, 8.8),
        Rule(161.0, 60.0, 9.3, 8.8), Rule(170.3, 60.0, 9.3, 8.8),
        Rule(49.9, 72.0, 38.8, 0), Rule(109.4, 72.0, 21.6, 0),
        Rule(13.5, 73.5, 174.4, 0),       # the band under the signature
        Rule(23.4, 78.9, 22.9, 6.5),      # doctor's number
        Rule(60.8, 78.9, 22.5, 6.5),      # pharmacy's number
        Rule(106.8, 78.9, 25.8, 6.5),     # prescription number
        Rule(152.8, 74.3, 8.8, 11.3), Rule(161.6, 74.3, 8.9, 11.3),
        Rule(170.5, 74.3, 9.1, 11.3),
        Rule(34.0, 90.5, 70.5, 5.5), Rule(128.5, 90.5, 57.5, 5.5),
        # the funder's columns beside the drug table: a heading cell and a
        # body cell each, which is the grid without thirty rectangles.
        Rule(133.6, 98.1, 15.7, 5.2), Rule(133.6, 103.3, 15.7, 31.9),
        Rule(149.3, 98.1, 16.1, 5.2), Rule(149.3, 103.3, 16.1, 31.9),
        Rule(165.4, 98.1, 9.9, 5.2), Rule(165.4, 103.3, 9.9, 31.9),
        Rule(175.3, 98.1, 4.8, 5.2), Rule(175.3, 103.3, 4.8, 31.9),
        Rule(180.1, 98.1, 7.8, 5.2), Rule(180.1, 103.3, 7.8, 31.9),
        Rule(112.0, 136.4, 15.2, 5.0),    # the gross, under CHARGE
        Rule(13.5, 183.2, 174.4, 0),      # under the counselling name and date
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
    "form": (203.2, 279.4),      # the continuous stationery's own size
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
    # Where the row's top rule sits above its baseline. Measured, like the
    # pitch: a value on the stationery sits 1.7mm above the line under it, so
    # the line above it is a row height further up.
    lift = g.row_height - 1.7
    c.setLineWidth(0.4)
    for n in range(g.rows + 1):
        y = g.top - lift + n * g.row_height
        x1, y1 = at(left, y)
        x2, _ = at(right, y)
        c.line(x1, y1, x2, y1)
    top_y = at(left, g.top - lift)[1]
    bot_y = at(left, g.top - lift + g.rows * g.row_height)[1]
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
            # The line number is pre-printed on the stationery, so the overlay
            # never supplies one. On blank paper nothing has printed it yet.
            text = row.get(key, "")
            if key == "line_no" and not text:
                text = f"{n + 1:02d}"
            value(text,
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
