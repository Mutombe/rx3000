"""The dispensing shorthand, as a sheet somebody can hand to an inspector.

An inspector asking about abbreviations is asking one question: can a code this
pharmacy uses be misread by the person who ends up holding the box? So the
sheet answers that first, in a paragraph at the top, and only then lists the
codes. The list on its own would be a glossary; a glossary does not say what
happens to the abbreviation between the keyboard and the label.

It is also the sheet a new dispenser is handed on their first morning, which is
why the caution column is written in plain sentences rather than symbols. A
legend that needs its own legend gets left in a drawer.

Pure reportlab, no system libraries: a pharmacy server should not need GTK
installed to produce one page of A4.
"""
from __future__ import annotations

import io
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle)

INK = colors.HexColor("#16161d")
MID = colors.HexColor("#4a4956")
FAINT = colors.HexColor("#7c7b87")
LINE = colors.HexColor("#d9d9e0")
WASH = colors.HexColor("#f2f2f6")
WARN = colors.HexColor("#8a5a12")
WARN_BG = colors.HexColor("#fdf4e6")

TITLES = {
    "quantity": "How much",
    "frequency": "How often",
    "timing": "When",
    "route": "Where it goes",
    "form": "What it is",
}

#: The paragraph an inspector is actually asking for, and the reason the rest
#: of the sheet is a glossary rather than a defence.
PRINCIPLE = (
    "No abbreviation on this sheet is ever printed on a medicine label. Every "
    "code is expanded into full words at the moment it is typed, and the label "
    "carries only those words. A dispenser types <b>1t tds pc</b> and the box "
    "reads <b>Take ONE tablet three times a day after food.</b> The shorthand "
    "exists to save keystrokes at the counter; it does not leave the counter."
)

WHY_IT_MATTERS = (
    "Abbreviations cause dispensing errors when they are read by somebody other "
    "than the person who wrote them &mdash; a patient at home, a nurse on a "
    "ward, a locum the following morning. Expanding at the point of entry means "
    "the only person who ever reads a code is the dispenser who typed it, "
    "seconds after typing it. Where a code can still be read two ways by that "
    "dispenser, it is marked below and the safer alternative is named."
)


def _styles():
    base = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle("h1", parent=base["Title"], fontName="Helvetica-Bold",
                             fontSize=17, leading=21, textColor=INK,
                             alignment=TA_LEFT, spaceAfter=2),
        "sub": ParagraphStyle("sub", parent=base["Normal"], fontName="Helvetica",
                              fontSize=9, leading=13, textColor=FAINT),
        "body": ParagraphStyle("body", parent=base["Normal"], fontName="Helvetica",
                               fontSize=9.2, leading=13.4, textColor=MID),
        "h2": ParagraphStyle("h2", parent=base["Normal"],
                             fontName="Helvetica-Bold", fontSize=10, leading=13,
                             textColor=INK, spaceBefore=9, spaceAfter=4),
        "cell": ParagraphStyle("cell", parent=base["Normal"], fontName="Helvetica",
                               fontSize=8.6, leading=11.4, textColor=INK),
        "cellmid": ParagraphStyle("cellmid", parent=base["Normal"],
                                  fontName="Helvetica", fontSize=8.6,
                                  leading=11.4, textColor=MID),
        "code": ParagraphStyle("code", parent=base["Normal"],
                               fontName="Courier-Bold", fontSize=9,
                               leading=11.4, textColor=INK),
        "warn": ParagraphStyle("warn", parent=base["Normal"], fontName="Helvetica",
                               fontSize=8.2, leading=10.8, textColor=WARN),
    }


def build(book: dict, *, pharmacy: str, branch: str = "",
          printed_by: str = "") -> bytes:
    """Render the grouped code book to PDF bytes.

    `book` is what `sig.book()` returns, so the sheet and the picker on screen
    can never drift: an inspector's copy that disagreed with the software would
    be worse than no copy at all.
    """
    st = _styles()
    buf = io.BytesIO()

    def furniture(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.5)
        canvas.line(18 * mm, 16 * mm, A4[0] - 18 * mm, 16 * mm)
        canvas.setFont("Helvetica", 7.6)
        canvas.setFillColor(FAINT)
        canvas.drawString(18 * mm, 11 * mm,
                          f"{pharmacy}{' · ' + branch if branch else ''}"
                          f" · dispensing shorthand"
                          f" · {date.today():%d %B %Y}")
        canvas.drawRightString(A4[0] - 18 * mm, 11 * mm, f"Page {doc.page}")
        canvas.restoreState()

    doc = BaseDocTemplate(buf, pagesize=A4,
                          leftMargin=18 * mm, rightMargin=18 * mm,
                          topMargin=16 * mm, bottomMargin=20 * mm,
                          title=f"{pharmacy} — dispensing shorthand",
                          author=pharmacy)
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
                  id="body", showBoundary=0)
    doc.addPageTemplates([PageTemplate(id="all", frames=[frame],
                                       onPage=furniture)])

    flow = [
        Paragraph("Dispensing shorthand", st["h1"]),
        Paragraph(
            f"{pharmacy}{' &middot; ' + branch if branch else ''} &middot; "
            f"{book.get('count', 0)} codes in use &middot; "
            f"printed {date.today():%d %B %Y}"
            + (f" by {printed_by}" if printed_by else ""),
            st["sub"]),
        Spacer(1, 9),
    ]

    # The statement first. The list is the appendix to it, not the other way up.
    box = Table([[Paragraph(PRINCIPLE, st["body"])]], colWidths=[doc.width])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), WASH),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    flow += [box, Spacer(1, 7), Paragraph(WHY_IT_MATTERS, st["body"]),
             Spacer(1, 4)]

    widths = [22 * mm, 58 * mm, 30 * mm, doc.width - 110 * mm]
    for category, codes in book.get("groups", {}).items():
        flow.append(Paragraph(TITLES.get(category, category.title()), st["h2"]))
        rows = [[Paragraph("<b>Code</b>", st["cellmid"]),
                 Paragraph("<b>Prints on the label</b>", st["cellmid"]),
                 Paragraph("<b>Origin</b>", st["cellmid"]),
                 Paragraph("<b>Read it twice</b>", st["cellmid"])]]
        flagged: list[int] = []
        for c in codes:
            if c.get("caution"):
                flagged.append(len(rows))
            rows.append([
                Paragraph(c["code"], st["code"]),
                Paragraph(c["expansion"], st["cell"]),
                Paragraph(c.get("meaning") or "&mdash;", st["cellmid"]),
                Paragraph(c.get("caution") or "", st["warn"]),
            ])
        table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
        style = [
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.6, LINE),
            ("LINEBELOW", (0, 1), (-1, -2), 0.25, LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]
        # A flagged row is tinted rather than starred. An inspector reading down
        # the page should not have to find a key at the bottom to know which
        # lines are the ones they came for.
        for r in flagged:
            style.append(("BACKGROUND", (0, r), (-1, r), WARN_BG))
        table.setStyle(TableStyle(style))
        flow.append(table)

    flow += [
        Spacer(1, 10),
        Paragraph(
            "Codes are held per pharmacy and may be added to or edited; this "
            "sheet is generated from the book in force on the date shown, so a "
            "reprint always matches what the dispensary is actually using. "
            "Retired codes stop being offered but keep expanding, so a script "
            "dispensed under an older book still reads correctly in the "
            "history.", st["sub"]),
    ]

    doc.build(flow)
    return buf.getvalue()
