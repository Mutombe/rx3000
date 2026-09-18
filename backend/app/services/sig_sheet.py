"""The dispensing shorthand, as a sheet somebody can hand to an inspector.

An inspector asking about abbreviations is asking one question: can a code this
pharmacy uses be misread by the person who ends up holding the box? So the
sheet answers that first, in a paragraph at the top, and only then lists the
codes. The list on its own would be a glossary; a glossary does not say what
happens to the abbreviation between the keyboard and the label.

It is also the sheet a new dispenser is handed on their first morning, which is
why the caution column is written in plain sentences rather than symbols. A
legend that needs its own legend gets left in a drawer.

Set through `brand`, like everything else RX5000 puts on paper. This sheet used
to carry its own greys and its own Helvetica, so an inspector handed it and a
claim copy on the same morning was handed two documents that did not look like
they came from the same company.

Pure reportlab, no system libraries: a pharmacy server should not need GTK
installed to produce one page of A4.
"""
from __future__ import annotations

import io
from datetime import date

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle)

from . import brand

INK = brand.INK
MID = brand.SOFT
FAINT = brand.FAINT
LINE = brand.RULE
WASH = brand.TINT
WARN = brand.STOP
WARN_BG = brand.TINT

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
    "than the person who wrote them: a patient at home, a nurse on a "
    "ward, a locum the following morning. Expanding at the point of entry means "
    "the only person who ever reads a code is the dispenser who typed it, "
    "seconds after typing it. Where a code can still be read two ways by that "
    "dispenser, it is marked below and the safer alternative is named."
)


def _styles():
    """The brand's styles, under the names this sheet already calls them.

    Mapped rather than renamed throughout: the table below is the part an
    inspector reads and it has been proof-read against real code books. A
    rename would have touched every row of it to change nothing anybody sees.
    """
    st = brand.styles()
    return {
        "h1": st["title"], "sub": st["sub"], "body": st["body"],
        "h2": st["section"], "cell": st["strong"], "cellmid": st["small"],
        "code": st["mono"], "warn": st["warn"],
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

    # A single-branch pharmacy usually names its branch after itself, and the
    # header then read "RX5000 Pharmacy Central · RX5000 Pharmacy Central".
    # Saying it twice does not make it truer.
    if branch.strip().lower() == pharmacy.strip().lower():
        branch = ""

    def furniture(canvas, d):
        brand.letterhead(
            canvas, d, kind="Dispensing shorthand",
            stamp=f"{book.get('count', 0)} codes · {date.today():%d %b %Y}",
            footer_left=f"{pharmacy}{' · ' + branch if branch else ''}",
            footer_right="Expanded in full on every label printed.")

    doc = BaseDocTemplate(buf, pagesize=A4,
                          leftMargin=16 * mm, rightMargin=16 * mm,
                          topMargin=32 * mm, bottomMargin=20 * mm,
                          title=f"{pharmacy}, dispensing shorthand",
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
                Paragraph(c.get("meaning") or "", st["cellmid"]),
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
