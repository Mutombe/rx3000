"""The claim copy — the sheet of paper a dispensing leaves behind.

WHAT THIS IS FOR

Three readers, and they want the same facts for different reasons:

  the funder      wants to see what was dispensed, to whom, on whose
                  authority, and what it is being asked to pay;
  the inspector   wants to see that a schedule 3 and above went out against a
                  prescriber and a date, and who handed it over;
  the pharmacy    wants, six months later, to answer "what did she get in
                  March" without opening a database.

So it is one page, it repeats nothing, and every figure on it is the figure the
sale actually carried rather than a price looked up now — a copy that reprices
itself when the shelf price changes is a copy that cannot settle an argument.

WHY A PDF AND NOT A PRINTED WEB PAGE

It goes to a laser in a back office, on A4, and it has to look the same in six
months from a file as it did on the day. A browser's print of an HTML page
depends on the browser, its margins, and whether somebody had the sidebar open.

It is also the reason the desktop shell needs `print_page` rather than
`print_raw`: this is a document with a driver behind it, not a stream of bytes
a thermal head interprets.
"""
from __future__ import annotations

import io
from datetime import date, datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

INK = colors.HexColor("#16161d")
MID = colors.HexColor("#4a4956")
RULE = colors.HexColor("#c9c9d2")
BAND = colors.HexColor("#f1f1f4")


def _styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=15,
                                textColor=INK, spaceAfter=1, alignment=0),
        "sub": ParagraphStyle("s", parent=base["Normal"], fontSize=8.5,
                              textColor=MID, spaceAfter=6),
        "h": ParagraphStyle("h", parent=base["Normal"], fontSize=7.5,
                            textColor=MID, spaceAfter=1),
        "b": ParagraphStyle("b", parent=base["Normal"], fontSize=9.5,
                            textColor=INK, leading=12),
        "cell": ParagraphStyle("c", parent=base["Normal"], fontSize=8.5,
                               textColor=INK, leading=11),
        "foot": ParagraphStyle("f", parent=base["Normal"], fontSize=7.5,
                               textColor=MID, leading=10),
    }


def _pair(st, label, value):
    return [Paragraph(label.upper(), st["h"]),
            Paragraph(str(value or "—"), st["b"])]


def build(*, pharmacy: str, pharmacy_reg: str = "", pharmacy_address: str = "",
          rx_number: str, dispensed_at: datetime | None,
          patient_name: str, patient_id: str = "", medical_aid: str = "",
          membership_no: str = "", doctor_name: str = "",
          doctor_practice: str = "", branch: str = "", dispensed_by: str = "",
          lines: list[dict], total: float = 0.0) -> bytes:
    """One A4 page. `lines` carry the figures the sale recorded, not today's."""
    st = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=14 * mm, bottomMargin=14 * mm,
        title=f"Claim copy {rx_number}", author=pharmacy)

    flow = []
    flow.append(Paragraph(pharmacy, st["title"]))
    bits = [x for x in (pharmacy_address, f"Reg {pharmacy_reg}" if pharmacy_reg else "",
                        branch) if x]
    flow.append(Paragraph(" &middot; ".join(bits), st["sub"]))

    flow.append(Paragraph("CLAIM COPY", ParagraphStyle(
        "k", parent=st["b"], fontSize=11, textColor=INK, spaceAfter=6)))

    when = dispensed_at or datetime.utcnow()
    head = Table([
        _pair(st, "Script number", rx_number)
        + _pair(st, "Dispensed", when.strftime("%d %b %Y %H:%M"))
        + _pair(st, "Dispensed by", dispensed_by),
    ], colWidths=[28 * mm, 34 * mm, 28 * mm, 30 * mm, 28 * mm, 30 * mm])
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
    ]))
    flow.append(head)

    who = Table([
        _pair(st, "Patient", patient_name) + _pair(st, "ID number", patient_id),
        _pair(st, "Medical aid", medical_aid) + _pair(st, "Membership", membership_no),
        _pair(st, "Prescriber", doctor_name) + _pair(st, "Practice number", doctor_practice),
    ], colWidths=[28 * mm, 62 * mm, 28 * mm, 60 * mm])
    who.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, RULE),
    ]))
    flow.append(who)
    flow.append(Spacer(1, 4 * mm))

    # The dispensed lines. Quantity is in dispensable units and the unit price
    # is per unit, which is what the sale recorded — the two have to agree on
    # this page or it settles nothing.
    body = [[Paragraph(h, st["h"]) for h in
             ("MEDICINE", "QTY", "UNIT", "TOTAL", "DIRECTIONS")]]
    for ln in lines:
        body.append([
            Paragraph(str(ln.get("description", "")), st["cell"]),
            Paragraph(f"{ln.get('quantity', 0)}", st["cell"]),
            Paragraph(f"{ln.get('unit_price', 0):.4f}".rstrip("0").rstrip("."), st["cell"]),
            Paragraph(f"{ln.get('line_total', 0):.2f}", st["cell"]),
            Paragraph(str(ln.get("directions", "")), st["cell"]),
        ])
    table = Table(body, colWidths=[52 * mm, 12 * mm, 18 * mm, 20 * mm, 76 * mm],
                  repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BAND),
        ("LINEBELOW", (0, 0), (-1, 0), 0.6, RULE),
        ("LINEBELOW", (0, 1), (-1, -1), 0.3, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (1, 1), (3, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ]))
    flow.append(table)

    flow.append(Spacer(1, 3 * mm))
    tot = Table([[Paragraph("TOTAL", st["h"]),
                  Paragraph(f"<b>{total:.2f}</b>", st["b"])]],
                colWidths=[160 * mm, 18 * mm])
    tot.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "RIGHT"),
        ("LINEABOVE", (1, 0), (1, 0), 0.6, RULE),
    ]))
    flow.append(tot)

    flow.append(Spacer(1, 10 * mm))
    # A signature line, because a claim copy is signed for on collection and a
    # copy with nowhere to sign gets signed across the medicine list.
    sign = Table([[Paragraph("RECEIVED BY", st["h"]), "",
                   Paragraph("DATE", st["h"]), ""]],
                 colWidths=[26 * mm, 76 * mm, 16 * mm, 40 * mm])
    sign.setStyle(TableStyle([
        ("LINEBELOW", (1, 0), (1, 0), 0.5, RULE),
        ("LINEBELOW", (3, 0), (3, 0), 0.5, RULE),
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    flow.append(sign)

    flow.append(Spacer(1, 6 * mm))
    flow.append(Paragraph(
        f"Produced by RX5000 on {date.today():%d %b %Y}. The figures shown are "
        f"those recorded against this dispensing and do not change if a shelf "
        f"price changes afterwards.", st["foot"]))

    doc.build(flow)
    return buf.getvalue()
