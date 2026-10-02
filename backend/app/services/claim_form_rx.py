"""Our own claim form: the same claim, designed rather than inherited.

WHY THIS EXISTS BESIDE claim_form.py

`claim_form.py` reproduces somebody else's stationery, because that is the
sheet the funders accept and its layout is not ours to argue with. It is a
1970s form: everything boxed, every label in the same weight as every value,
the amount claimed no louder than the suffix beside it, and a third of the page
spent on ruling.

This is the same information set the way RX5000 sets a document. It is for the
pharmacy that wants its claim to look like the rest of its paperwork, for a
scheme that takes a printed claim, and for the file copy somebody actually
reads. It is NOT a drop-in for a funder who insists on the bought form.

WHAT IT DOES DIFFERENTLY, AND WHY EACH ONE

  THE AMOUNT IS THE LOUDEST THING ON THE PAGE. A clerk processing forty claims
  is looking for one number. On the original it is 9pt Courier in a box the
  same size as the dependant suffix.

  LABELS RECEDE AND VALUES CARRY. Small letterspaced caps in grey above the
  value, rather than a caption the same size as the thing it names. The eye
  lands on content.

  THE FUNDER'S HALF IS VISIBLY NOT OURS. AWARD, SHORTFALL and REASON live in
  their own panel, drawn in grey and headed FOR THE FUNDER, so nobody in the
  dispensary fills in a box that is not theirs. On the original they are a
  second grid welded to the first, and pharmacies write in them.

  ONE TABLE, TINTED, NOT RULED. Thirty rules is a timetable. A tint on
  alternate rows lets the eye track one medicine across the page.

  THE COUNSELLING HALF IS THE PATIENT'S. It is set at reading size with room
  around it, because that half is torn off and taken home, and on the original
  it is the same 8pt as the funder's columns.

THE WORDMARK IS THE PHARMACY'S

Same rule the printed documents already follow: a claim leaves the pharmacy
carrying the pharmacy's name, not ours. The RX5000 mark sits at the foot where
a printer's imprint goes. What is ours here is the design language, which is
`brand.py` and shared with every other sheet this system prints.
"""
from __future__ import annotations

import io

from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfgen import canvas

from . import brand

#: A4, which is what is in the tray. The bought form is 8 by 11 inches and this
#: one is deliberately not: it has no stationery to line up with.
PAGE = (210.0, 297.0)
#: The measure. Everything starts at LEFT and ends at RIGHT, and nothing on the
#: page is allowed its own margin.
LEFT, RIGHT = 16.0, 194.0
MEASURE = RIGHT - LEFT
#: Where the imprint sits, and therefore the line nothing else may cross.
FOOT = 287.0


def _text_width(text: str, font: str, size: float, space: float = 0.0) -> float:
    """Millimetres, including any letterspacing we have asked for."""
    w = pdfmetrics.stringWidth(text, font, size)
    if space:
        w += space * max(len(text) - 1, 0)
    return w / mm


class Sheet:
    """A canvas that measures in millimetres from the top of the page.

    Every coordinate in this file is read the way somebody holding a ruler
    against the sheet reads it. Doing the flip once here is the difference
    between a layout you can reason about and one you debug upside down.
    """

    def __init__(self, c: canvas.Canvas):
        self.c = c
        self.h = PAGE[1]

    # -- primitives ---------------------------------------------------------
    def text(self, x, y, s, font="Manrope-Regular", size=9.5, colour=None,
             align="left", space=0.0):
        if not s:
            return
        s = str(s)
        px, py = x * mm, (self.h - y) * mm
        if align == "right":
            px -= _text_width(s, font, size, space) * mm
        elif align == "centre":
            px -= _text_width(s, font, size, space) * mm / 2
        # A text object rather than drawString, because letterspacing is set on
        # the text object and the small caps labels this page is built from are
        # unreadable without it.
        t = self.c.beginText(px, py)
        t.setFont(font, size)
        t.setFillColor(colour if colour is not None else brand.BODY)
        # ALWAYS, even for zero. Character spacing is PDF text state and it
        # survives BT/ET, so setting it only when it is wanted leaves every
        # later string wearing the last label's letterspacing. It cost the
        # member's declaration 27mm and ran it off the right of the page,
        # while stringWidth, which knows nothing of the graphics state, went
        # on reporting a line that fitted.
        t.setCharSpace(space)
        t.textOut(s)
        self.c.drawText(t)

    def rule(self, x1, y, x2, colour=None, width=0.6):
        self.c.setStrokeColor(colour if colour is not None else brand.RULE)
        self.c.setLineWidth(width)
        self.c.line(x1 * mm, (self.h - y) * mm, x2 * mm, (self.h - y) * mm)

    def panel(self, x, y, w, h, fill=None, stroke=None, radius=2.0):
        if fill is not None:
            self.c.setFillColor(fill)
        if stroke is not None:
            self.c.setStrokeColor(stroke)
            self.c.setLineWidth(0.6)
        self.c.roundRect(x * mm, (self.h - y - h) * mm, w * mm, h * mm,
                         radius * mm, stroke=1 if stroke is not None else 0,
                         fill=1 if fill is not None else 0)

    # -- the one compound thing the page is made of -------------------------
    def field(self, x, y, label, value, width=None, size=10.0, align="left",
              strong=True, blank=False):
        """A small grey label with the value under it.

        The whole layout is this, repeated. A label is 6.6pt letterspaced caps
        in the faint grey; a value is Semibold at reading size in the body ink.
        Nothing on the page is a caption beside a value, because that is what
        makes the original hard to read at a glance.

        `blank` is a field nobody has filled in yet and nobody was meant to:
        a signature, a date somebody signs beside it. It draws the rule and
        says nothing, where a missing value says so in words.
        """
        self.text(x, y, label.upper(), "Manrope-Semibold", 6.6, brand.FAINT,
                  align=align, space=0.55)
        missing = value in (None, "")
        if not (blank and missing):
            self.text(x, y + 5.2, value if not missing else "not given",
                      "Manrope-Semibold" if strong and not missing
                      else "Manrope-Regular",
                      size, brand.FAINT if missing else brand.BODY, align=align)
        if width:
            self.rule(x if align == "left" else x - width, y + 7.4,
                      (x + width) if align == "left" else x)


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    """Break a line to the measure, in millimetres."""
    words, lines, run = str(text).split(), [], ""
    for word in words:
        trial = f"{run} {word}".strip()
        if run and _text_width(trial, font, size) > width:
            lines.append(run)
            run = word
        else:
            run = trial
    if run:
        lines.append(run)
    return lines


def render(values: dict, lines: list[dict], counselling: list[str]) -> bytes:
    """The claim, on A4, in the house style. Same inputs as the overlay."""
    brand.use_fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(PAGE[0] * mm, PAGE[1] * mm))
    c.setTitle("Medical aid drug claim")
    s = Sheet(c)

    # ------------------------------------------------------------ letterhead
    # The pharmacy's name, because the claim is the pharmacy's. What is ours is
    # everything about how it is set.
    s.text(LEFT, 20.0, values.get("pharmacy_name") or "", "Manrope-Extrabold",
           17, brand.INK)
    under = " · ".join(x for x in (values.get("footer_2"),
                                   values.get("footer_3"),
                                   values.get("footer_4")) if x)
    s.text(LEFT, 25.6, under, "Manrope-Regular", 8, brand.SOFT)

    s.text(RIGHT, 18.4, "MEDICAL AID DRUG CLAIM", "Manrope-Bold", 9.5,
           brand.NAVY, align="right", space=0.5)
    s.text(RIGHT, 23.0, "Certified copy of doctor's prescription",
           "Manrope-Regular", 7.6, brand.FAINT, align="right")
    s.rule(LEFT, 30.0, RIGHT, brand.INK, 0.9)

    def imprint() -> None:
        s.rule(LEFT, FOOT - 5.0, RIGHT, brand.RULE, 0.6)
        s.text(LEFT, FOOT, values.get("pharmacy_name") or "",
               "Manrope-Semibold", 7.4, brand.SOFT)
        s.text(RIGHT, FOOT, "Prepared on RX5000", "Manrope-Regular", 7.4,
               brand.FAINT, align="right")

    # ------------------------------------------------- the four facts, loudly
    # What a clerk opens the envelope looking for. The amount is the largest
    # thing on the sheet on purpose: on the bought form it is 9pt in a box the
    # same size as the dependant suffix.
    #
    # The amount sits behind its own rule rather than beside the date. It read
    # as one run of text with the date the first time, which on the one figure
    # the whole sheet exists to communicate is the worst place to be ambiguous.
    s.panel(LEFT, 35.0, MEASURE, 24.0, fill=brand.TINT)
    s.field(LEFT + 6, 42.5, "Medical scheme", values.get("medical_scheme"),
            size=11)
    s.field(LEFT + 60, 42.5, "Member number", values.get("member_number"),
            size=11)
    s.field(LEFT + 104, 42.5, "Claimed on", values.get("claim_date"), size=11)
    s.c.setStrokeColor(brand.RULE)
    s.c.setLineWidth(0.6)
    s.c.line((RIGHT - 48) * mm, (PAGE[1] - 39.0) * mm,
             (RIGHT - 48) * mm, (PAGE[1] - 55.0) * mm)
    s.text(RIGHT - 6, 42.5, "AMOUNT CLAIMED", "Manrope-Semibold", 6.6,
           brand.FAINT, align="right", space=0.55)
    s.text(RIGHT - 6, 53.0, f"$ {values.get('gross_claimed') or '0.00'}",
           "Manrope-Extrabold", 19, brand.INK, align="right")

    # --------------------------------------------- the patient and the member
    # Two columns, and nothing said twice: the scheme is in the strip above, so
    # the member's column carries what the strip does not.
    s.text(LEFT, 69.0, "THE PATIENT", "Manrope-Bold", 8.4, brand.NAVY,
           space=0.6)
    s.rule(LEFT, 71.4, LEFT + 84)
    s.field(LEFT, 78.0, "Full name", values.get("patient_name"))
    s.field(LEFT, 89.0, "Postal address", values.get("postal_address"))
    born = " ".join(x for x in (values.get("birth_day"),
                                values.get("birth_month"),
                                values.get("birth_year")) if x)
    s.field(LEFT, 100.0, "Date of birth", born)

    s.text(LEFT + 100, 69.0, "THE MEMBER", "Manrope-Bold", 8.4, brand.NAVY,
           space=0.6)
    s.rule(LEFT + 100, 71.4, RIGHT)
    s.field(LEFT + 100, 78.0, "Surname", values.get("member_surname"))
    s.field(LEFT + 100, 89.0, "Initials", values.get("member_initials"))
    s.field(LEFT + 100, 100.0, "Dependant code",
            values.get("dependant_suffix"))

    # ----------------------------------------- who prescribed, who dispensed
    s.panel(LEFT, 109.0, MEASURE, 19.0, stroke=brand.RULE)
    s.field(LEFT + 6, 116.0, "Prescriber", values.get("doctor_name"))
    s.field(LEFT + 68, 116.0, "Practice no.", values.get("doctor_no"))
    s.field(LEFT + 112, 116.0, "Pharmacy no.", values.get("pharmacy_no"))
    s.field(RIGHT - 6, 116.0, "Script no.", values.get("prescription_no"),
            align="right")

    # ------------------------------------------------------- what went out
    s.text(LEFT, 134.0, "WHAT WAS DISPENSED", "Manrope-Bold", 8.4,
           brand.NAVY, space=0.6)
    head = 140.0
    for x, align, label in ((LEFT + 7, "left", "Medicine"),
                            (LEFT + 81, "left", "Code"),
                            (LEFT + 121, "right", "Qty"),
                            (LEFT + 127, "left", "Supplied"),
                            (RIGHT, "right", "Charge")):
        s.text(x, head, label.upper(), "Manrope-Semibold", 6.6, brand.FAINT,
               align=align, space=0.55)
    s.rule(LEFT, head + 2.0, RIGHT, brand.INK, 0.9)

    rows = [r for r in lines if (r.get("drug") or "").strip()]
    row_h, y = 8.6, head + 2.0
    for n, row in enumerate(rows):
        if n % 2 == 1:
            s.panel(LEFT, y, MEASURE, row_h, fill=brand.TINT, radius=0.8)
        base = y + 6.0
        s.text(LEFT + 1, base, f"{n + 1}", "Manrope-Semibold", 8, brand.FAINT)
        s.text(LEFT + 7, base, row.get("drug") or "", "Manrope-Semibold", 9.5)
        s.text(LEFT + 81, base, row.get("price_code") or "",
               "Manrope-Regular", 9, brand.SOFT)
        s.text(LEFT + 121, base, row.get("quantity") or "",
               "Manrope-Semibold", 9.5, align="right")
        when = "/".join(x for x in (row.get("day"), row.get("month"),
                                    row.get("year")) if x)
        s.text(LEFT + 127, base, when, "Manrope-Regular", 9, brand.SOFT)
        s.text(RIGHT, base, row.get("charge") or "", "Manrope-Semibold", 9.5,
               align="right")
        y += row_h

    s.rule(LEFT, y, RIGHT, brand.INK, 0.9)
    s.text(RIGHT - 32, y + 6.4, "GROSS", "Manrope-Semibold", 8, brand.FAINT,
           align="right", space=0.55)
    s.text(RIGHT, y + 6.6, f"$ {values.get('gross_total') or '0.00'}",
           "Manrope-Extrabold", 12, brand.INK, align="right")
    y += 11.0

    # ------------------------------------------------------ the funder's half
    # Grey, panelled and headed, because the dispensary must not write in it.
    s.panel(LEFT, y, MEASURE, 20.5, stroke=brand.RULE)
    s.text(LEFT + 6, y + 6.4, "FOR THE FUNDER", "Manrope-Bold", 7.4,
           brand.FAINT, space=0.6)
    s.text(LEFT + 44, y + 6.4, "Leave blank. The scheme completes this.",
           "Manrope-Regular", 7.4, brand.FAINT)
    funder = (("Claim number", 36), ("Award", 24), ("Shortfall", 24),
              ("Reason", 30), ("Date stamp", 24))
    fx = LEFT + 6
    for label, w in funder:
        s.text(fx, y + 13.4, label.upper(), "Manrope-Semibold", 6.2,
               brand.FAINT, space=0.5)
        s.rule(fx, y + 17.6, fx + w)
        fx += w + 6
    y += 27.0

    # -------------------------------------------- the member's declaration
    for part in _wrap(
            "I confirm that the details above are correct and that this claim "
            "is lodged against my medical aid society in the utmost good "
            "faith. I confirm that the amount claimed is not claimable from "
            "another source, and I understand that no award is payable until "
            "my society has received contributions for the stated period of "
            "treatment.", "Manrope-Regular", 7.6, MEASURE):
        s.text(LEFT, y, part, "Manrope-Regular", 7.6, brand.SOFT)
        y += 4.0
    y += 7.5
    s.field(LEFT, y, "Member's signature", "", width=76, blank=True)
    s.field(LEFT + 100, y, "Date", "", width=60, blank=True)
    y += 13.0

    # ---------------------------------------------------- the patient's half
    # The tear-off. It is the half the patient takes home, so it is set at
    # reading size and never squeezed to save a page: if the script is long
    # enough to push it over, it gets a page of its own rather than a footer
    # printed through it.
    said = [t for t in counselling if (t or "").strip()]
    wrapped = [_wrap(t, "Manrope-Regular", 9.5, MEASURE - 6) for t in said]
    needs = 19.0 + sum(len(w) * 5.0 + 2.2 for w in wrapped)
    if y + needs > FOOT - 8.0:
        imprint()
        c.showPage()
        y = 24.0

    s.rule(LEFT, y, RIGHT, brand.RULE, 0.6)
    s.text(LEFT, y + 7.0, "PATIENT COUNSELLING", "Manrope-Extrabold", 13,
           brand.INK)
    s.text(RIGHT, y + 6.6, values.get("counsel_date") or "",
           "Manrope-Regular", 8.6, brand.SOFT, align="right")
    s.text(LEFT, y + 12.4, "A guide only. Where this differs from what your "
           "doctor told you, follow your doctor.", "Manrope-Regular", 8.2,
           brand.SOFT)
    y += 18.0
    for parts in wrapped:
        for i, part in enumerate(parts):
            s.text(LEFT + 3, y, part,
                   "Manrope-Semibold" if i == 0 else "Manrope-Regular", 9.5)
            y += 5.0
        y += 2.2

    imprint()
    c.showPage()
    c.save()
    return buf.getvalue()
