"""The medicine schedules of this jurisdiction, as a sheet for the counter wall.

A dispenser who has come off another system knows the old codes and reads the
new ones as the old ones. That is the dangerous case, and it is specific: in
South Africa the codes are numbered S0 to S6 and the number tells you how
restricted something is. In Zimbabwe they are not numbered at all, and "P" is
less restricted than "PP" for reasons a number would have made obvious and a
letter does not.

So the sheet is ordered loosest first, and every row says the one thing that
actually changes at the counter: whether a script is needed, whether a
pharmacist must be involved, and whether it goes in the register.

Built from the jurisdiction pack rather than typed out, so a sheet pinned to a
wall cannot disagree with the software that printed it. A pharmacy that switches
pack gets the other country's sheet from the same code.

Set through `brand`, like everything else RX5000 puts on paper. A reference
sheet that arrived in Helvetica beside a claim copy set in Manrope would look
like two companies had written to the same pharmacy.
"""
from __future__ import annotations

import io
from datetime import date

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import (BaseDocTemplate, Frame, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle)

from . import brand

#: What the sheet is for, said before the table rather than after it.
PRINCIPLE = (
    "These are the classifications this pharmacy dispenses under, and they are "
    "<b>not</b> the South African S0 to S6 scale. The codes here are letters, "
    "not numbers, so nothing about the code itself tells you how restricted a "
    "medicine is. <b>P</b> is less restricted than <b>PP</b>, and "
    "<b>PP10</b> is tighter than both. Read the row, not the letters."
)

#: The column that matters, spelled out once so the table can stay terse.
HOW_TO_READ = (
    "The rows run from freest to tightest. A medicine&rsquo;s classification "
    "decides three things at the counter: whether a prescription is needed, "
    "whether a pharmacist has to be involved, and whether the hand-over is "
    "written into the register. Everything else follows from those."
)

WATCH_FOR = (
    "A medicine that arrives from another system without a classification is "
    "filed under the freest code on this sheet, because an empty field and "
    "&ldquo;general sale&rdquo; are the same value in a database and not the "
    "same thing on a shelf. Before this sheet is relied on, check that the "
    "lines carrying the top code are genuinely general sale rather than merely "
    "unclassified."
)


def _needs(policy) -> str:
    """The things that change at the counter, in the order they are met."""
    # A preparation nobody may dispense has no counter procedure, and printing
    # one invites somebody to follow it. The row says the only thing that is
    # true of it.
    if policy.route == "prohibited":
        return ("<b>Do not dispense.</b> Refer the prescriber. Refused by the "
                "software for everybody, including an administrator.")
    bits = ["Prescription" if policy.requires_prescription else "No prescription"]
    if policy.requires_pharmacist:
        bits.append("pharmacist")
    if policy.register_entry:
        bits.append("register entry")
    if policy.requires_id_verification:
        bits.append("ID checked")
    if policy.requires_script_sighted:
        bits.append("script sighted")
    if policy.requires_witness:
        bits.append("witness co-signs")
    if policy.requires_prescriber_verification:
        bits.append("prescriber confirmed")
    return ", ".join(bits)


def _repeats(policy) -> str:
    if policy.route == "prohibited":
        return "none"
    if policy.max_repeats < 0:
        return "no limit"
    if policy.max_repeats == 0:
        return "none"
    return f"up to {policy.max_repeats}"


def build(policies: list, *, pharmacy: str, country: str, branch: str = "",
          printed_by: str = "", counts: dict[str, int] | None = None) -> bytes:
    """Render the jurisdiction's schedules to PDF bytes.

    `policies` are the pack's own objects, so the sheet cannot drift from what
    the software enforces. `counts` is optional: how many products in this
    pharmacy carry each code, which turns a reference card into something a
    manager can act on.
    """
    st = brand.styles()
    buf = io.BytesIO()
    if branch.strip().lower() == pharmacy.strip().lower():
        branch = ""

    # One row per CODE, not per schedule number. Zimbabwe files 3 and 4 both as
    # PP, and a sheet listing PP twice would invite somebody to look for the
    # difference between them.
    seen: dict[str, object] = {}
    for policy in sorted(policies, key=lambda p: p.schedule):
        seen.setdefault(policy.code or f"S{policy.schedule}", policy)

    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=16 * mm, rightMargin=16 * mm,
        topMargin=32 * mm, bottomMargin=20 * mm,
        title=f"{pharmacy}, medicine schedules", author=pharmacy)

    def furniture(canvas, d):
        brand.letterhead(
            canvas, d, kind="Medicine schedules",
            stamp=f"{country} · {date.today():%d %b %Y}",
            footer_left=pharmacy,
            footer_right="Classifications as enforced by this software.")

    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
                  id="body", showBoundary=0)
    doc.addPageTemplates([PageTemplate(id="all", frames=[frame], onPage=furniture)])

    flow = [
        Paragraph(pharmacy, st["title"]),
        Paragraph(
            " &middot; ".join(x for x in (
                branch, country, f"{len(seen)} classifications",
                f"printed {date.today():%d %B %Y}"
                + (f" by {printed_by}" if printed_by else "")) if x),
            st["sub"]),
        Spacer(1, 5 * mm),
    ]

    # The warning before the table. The table is the appendix to it.
    notice = Table([[Paragraph(PRINCIPLE, st["body"])]], colWidths=[doc.width])
    notice.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), brand.TINT),
        ("LINEBEFORE", (0, 0), (0, -1), 2.2, brand.INK),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    flow += [notice, Spacer(1, 4 * mm),
             Paragraph(HOW_TO_READ, st["body"]), Spacer(1, 5 * mm)]

    header = ["CODE", "WHAT IT IS", "WHAT THE COUNTER MUST DO", "REPEATS"]
    if counts:
        header.append("LINES HERE")
    rows = [[Paragraph(h, st["head"]) for h in header]]

    tight: list[int] = []
    barred: list[int] = []
    for i, (code, policy) in enumerate(seen.items(), start=1):
        row = [
            Paragraph(code, st["mono"]),
            Paragraph(policy.label, st["strong"]),
            Paragraph(_needs(policy), st["small"]),
            Paragraph(_repeats(policy), st["small"]),
        ]
        if counts:
            n = counts.get(code, 0)
            row.append(Paragraph(f"{n:,}", st["small"]))
        rows.append(row)
        if policy.route == "controlled":
            tight.append(i)
        if policy.route == "prohibited":
            barred.append(i)

    widths = [17 * mm, 40 * mm, 70 * mm, 19 * mm]
    if counts:
        widths.append(22 * mm)
    # Scaled to the frame, so another column does not overhang the margin.
    scale = doc.width / sum(widths)
    table = Table(rows, colWidths=[w * scale for w in widths], repeatRows=1)
    style = brand.table_style(len(rows))
    style += [("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("TOPPADDING", (0, 1), (-1, -1), 7),
              ("BOTTOMPADDING", (0, 1), (-1, -1), 7)]
    # The rows where the law requires something of the person at the counter
    # carry a navy edge, so the eye finds them without reading the middle
    # column. Navy and not red: red means stop, and PP10 is dispensed every day.
    for i in tight:
        style.append(("LINEBEFORE", (0, i), (0, i), 2.2, brand.NAVY))
        style.append(("TEXTCOLOR", (0, i), (0, i), brand.NAVY))
    # Red is right here, and only here. This is the one row that means stop.
    for i in barred:
        style.append(("LINEBEFORE", (0, i), (0, i), 2.2, brand.STOP))
        style.append(("TEXTCOLOR", (0, i), (0, i), brand.STOP))
    table.setStyle(TableStyle(style))
    flow.append(table)

    flow += [Spacer(1, 6 * mm),
             Paragraph("What to watch for", st["section"]),
             Spacer(1, 1.5 * mm),
             Paragraph(WATCH_FOR, st["body"])]
    if counts:
        flow += [Spacer(1, 2 * mm),
                 Paragraph("The last column is how many lines in this pharmacy's "
                           "own catalogue carry each code today.", st["small"])]

    doc.build(flow)
    return buf.getvalue()
