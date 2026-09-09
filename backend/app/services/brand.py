"""One statement of what an RX5000 document looks like.

Everything this system prints on paper leaves the pharmacy carrying its name: a
claim copy a funder reads, a code sheet an inspector holds, a sign-in sheet
handed to staff. Three files were building their own headers, their own greys
and their own type, so the three looked like three different products.

They now come through here. A document is not decorated by adding a logo to it;
it is recognisable because everything on it — the ink, the rules, the type, the
way the foot of the page is set — is the same as on the last one.

THE PALETTE IS THE INTERFACE'S, SAMPLED FROM THE MARK

`#032153` is the ink the wordmark sets "RX" in, and `#12306b` is the lighter
navy beside it. Both are taken from the artwork rather than chosen to go with
it, which is why they match on screen and on paper without anybody maintaining
two lists.

THE RED IN THE LOGO IS NOT IN THE PALETTE, AND THAT IS DELIBERATE

The mark is navy and red. The interface uses red to mean stop — an expired
batch, a refused claim, a schedule 5 badge — so a brand red on a table rule or
a heading would be the one place the colour language contradicts itself. The
logo carries the red; the document carries the navy. The same rule the stylesheet
states, applied to paper so the two cannot drift.

TYPE

Manrope, in the weights the interface uses, converted to TrueType because
reportlab refuses PostScript outlines. Registered once here, so a document that
forgets to do it cannot silently fall back to Helvetica and look like somebody
else's letterhead.
"""
from __future__ import annotations

import pathlib

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image

ASSETS = pathlib.Path(__file__).resolve().parent.parent / "assets"
FONTS = ASSETS / "fonts"
LOGO = ASSETS / "logo-full.png"
MARK = ASSETS / "logo-mark.png"

# ---------------------------------------------------------------- the palette
#: The wordmark's own ink. Headings, and anything that carries the identity.
INK = colors.HexColor("#032153")
#: The lighter navy beside it. Section headings and accents.
NAVY = colors.HexColor("#12306b")
#: Body text. Near-black rather than the brand navy: a page set entirely in
#: brand colour reads as a brochure, and these are documents somebody works from.
BODY = colors.HexColor("#16161d")
SOFT = colors.HexColor("#4a4956")
FAINT = colors.HexColor("#8a8a99")
#: Rules and row tints, tinted toward the navy so they belong to it.
RULE = colors.HexColor("#d5dae6")
TINT = colors.HexColor("#f2f4f9")
#: State, kept outside the brand palette on purpose — see the module note.
STOP = colors.HexColor("#9e3226")
GO = colors.HexColor("#1f6b4f")

_registered = False


def use_fonts() -> str:
    """Register Manrope and return the body face's name.

    Idempotent: a process building three documents registers once. Falls back
    to Helvetica only if the files are genuinely absent, and says so by
    returning that name rather than pretending.
    """
    global _registered
    if _registered:
        return "Manrope-Regular"
    try:
        for weight in ("Regular", "Medium", "Semibold", "Bold", "Extrabold"):
            path = FONTS / f"Manrope-{weight}.ttf"
            pdfmetrics.registerFont(TTFont(f"Manrope-{weight}", str(path)))
        pdfmetrics.registerFontFamily(
            "Manrope-Regular", normal="Manrope-Regular", bold="Manrope-Bold",
            italic="Manrope-Regular", boldItalic="Manrope-Bold")
        _registered = True
        return "Manrope-Regular"
    except Exception:
        # A document that prints in Helvetica is worse than one that prints in
        # Manrope, and far better than one that does not print.
        return "Helvetica"


def styles() -> dict[str, ParagraphStyle]:
    """The paragraph styles every RX5000 document is set in."""
    use_fonts()
    return {
        "title": ParagraphStyle("t", fontName="Manrope-Extrabold", fontSize=19,
                                leading=22, textColor=INK, spaceAfter=1),
        "sub": ParagraphStyle("s", fontName="Manrope-Regular", fontSize=9,
                              leading=12, textColor=SOFT),
        "kind": ParagraphStyle("k", fontName="Manrope-Bold", fontSize=10.5,
                               leading=13, textColor=NAVY),
        "section": ParagraphStyle("sec", fontName="Manrope-Bold", fontSize=13,
                                  leading=16, textColor=NAVY),
        "head": ParagraphStyle("h", fontName="Manrope-Semibold", fontSize=7.4,
                               leading=9, textColor=FAINT),
        "body": ParagraphStyle("b", fontName="Manrope-Regular", fontSize=9.5,
                               leading=12.5, textColor=BODY),
        "strong": ParagraphStyle("st", fontName="Manrope-Semibold", fontSize=9.6,
                                 leading=12, textColor=BODY),
        "small": ParagraphStyle("sm", fontName="Manrope-Regular", fontSize=8.2,
                                leading=10.5, textColor=SOFT),
        "mono": ParagraphStyle("m", fontName="Manrope-Extrabold", fontSize=11.5,
                               leading=14, textColor=BODY),
        "warn": ParagraphStyle("w", fontName="Manrope-Medium", fontSize=9,
                               leading=12.5, textColor=STOP),
        "foot": ParagraphStyle("f", fontName="Manrope-Regular", fontSize=7.6,
                               leading=10, textColor=FAINT),
    }


def logo(height: float = 11 * mm) -> Image | None:
    """The wordmark, scaled to a height and keeping its proportions."""
    if not LOGO.exists():
        return None
    from reportlab.lib.utils import ImageReader

    w, h = ImageReader(str(LOGO)).getSize()
    return Image(str(LOGO), width=height * (w / h), height=height, mask="auto")


def letterhead(canvas, doc, *, kind: str = "", stamp: str = "",
               footer_left: str = "", footer_right: str = "",
               top: float = 30 * mm) -> None:
    """The band across the top of every page, and the line across the foot.

    Drawn on the canvas rather than flowed, so it repeats on page four without
    the document having to remember to add it — a second page with no
    letterhead is the page that gets separated from the rest and lost.
    """
    use_fonts()
    canvas.saveState()
    page_w, page_h = doc.pagesize

    art = logo(height=9 * mm)
    if art is not None:
        art.drawOn(canvas, doc.leftMargin, page_h - top + 3.5 * mm)

    if kind:
        canvas.setFont("Manrope-Bold", 9.5)
        canvas.setFillColor(NAVY)
        canvas.drawRightString(page_w - doc.rightMargin,
                               page_h - top + 8 * mm, kind.upper())
    if stamp:
        canvas.setFont("Manrope-Regular", 7.6)
        canvas.setFillColor(FAINT)
        canvas.drawRightString(page_w - doc.rightMargin,
                               page_h - top + 3.8 * mm, stamp)

    # A navy hairline under the band. One rule, the full measure, so every
    # document has the same horizon.
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.8)
    canvas.line(doc.leftMargin, page_h - top,
                page_w - doc.rightMargin, page_h - top)

    canvas.setFont("Manrope-Regular", 7.2)
    canvas.setFillColor(FAINT)
    if footer_left:
        canvas.drawString(doc.leftMargin, 11 * mm, footer_left)
    if footer_right:
        canvas.drawRightString(page_w - doc.rightMargin, 11 * mm, footer_right)
    canvas.drawCentredString(page_w / 2, 11 * mm, f"{canvas.getPageNumber()}")
    canvas.restoreState()


def table_style(rows: int, *, tint_alternate: bool = True) -> list:
    """The table every RX5000 document sets its rows in.

    A tint on alternate rows rather than a rule under each. Thirty ruled rows
    is a timetable; a tint lets the eye track one row across the page and keeps
    the sheet quiet enough that the content is the loudest thing on it.
    """
    style = [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 0.9, INK),
    ]
    if tint_alternate:
        style += [("BACKGROUND", (0, r), (-1, r), TINT)
                  for r in range(1, rows) if r % 2 == 0]
    return style
