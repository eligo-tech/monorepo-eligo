"""Draw the Kandidatenprofil page — and only draw it.

Pure: a `Sheet` and a `Branding` in, PDF bytes out. No database, no session,
no decision about WHAT is on the page; `service.py` makes those. That keeps
the layout testable on its own and the data rules out of the drawing code.

The shape follows the sample the agency sends today (ELI-20): the title top
left, the logo top right, a boxed "Angestrebte Position", a two-column table
(label · value, values in italics in the workspace colour), a boxed contact
line, and the company line with the AGB paragraph at the foot of every page.

ReportLab, not an HTML-to-PDF engine: it is pure Python with Pillow wheels,
so the slim production image needs no Cairo/Pango. Montserrat (SIL OFL 1.1,
`fonts/OFL.txt`) is embedded — the PDF looks the same on the client's machine
whatever fonts it has.
"""

from __future__ import annotations

import io
import pathlib
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_FONTS = pathlib.Path(__file__).resolve().parent / "fonts"
REGULAR, ITALIC, MEDIUM = "Montserrat", "Montserrat-Italic", "Montserrat-Medium"

_MARGIN_X = 18 * mm
_TOP = 14 * mm
_LABEL_WIDTH = 46 * mm
_TEXT = colors.HexColor("#333333")
_RULE = colors.HexColor("#1A1A1A")


def _register_fonts() -> None:
    if REGULAR in pdfmetrics.getRegisteredFontNames():
        return
    pdfmetrics.registerFont(TTFont(REGULAR, _FONTS / "Montserrat-Regular.ttf"))
    pdfmetrics.registerFont(TTFont(ITALIC, _FONTS / "Montserrat-Italic.ttf"))
    pdfmetrics.registerFont(TTFont(MEDIUM, _FONTS / "Montserrat-Medium.ttf"))
    pdfmetrics.registerFontFamily(
        REGULAR, normal=REGULAR, bold=MEDIUM, italic=ITALIC, boldItalic=ITALIC
    )


@dataclass(frozen=True)
class Bullet:
    text: str
    level: int = 0


@dataclass(frozen=True)
class Row:
    """One line of the table. `text` is prose, `bullets` a list; a row holds
    either, or both (text first)."""

    label: str
    text: str | None = None
    bullets: tuple[Bullet, ...] = ()


@dataclass(frozen=True)
class Sheet:
    #: "Kandidatenprofil – Nesim Celik"
    title: str
    position: str | None
    rows: tuple[Row, ...]
    #: "Kontakt: Thomas Bausch – t.bausch@… – 0151 …", or None for no box.
    contact: str | None


@dataclass(frozen=True)
class Branding:
    primary_color: str
    company_name: str | None = None
    company_line: str | None = None
    legal_text: str | None = None
    logo: bytes | None = field(default=None, repr=False)


def _p(text: str) -> str:
    """Plain text → ReportLab paragraph markup: escaped, line breaks kept."""
    return escape(text).replace("\r\n", "\n").replace("\n", "<br/>")


def _styles(primary: colors.Color) -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("base", fontName=REGULAR, fontSize=10, leading=13.5, textColor=_TEXT)
    return {
        "title": ParagraphStyle(
            "title", parent=base, fontSize=16, leading=20, textColor=primary
        ),
        "label": ParagraphStyle("label", parent=base),
        "value": ParagraphStyle("value", parent=base, fontName=ITALIC, textColor=primary),
        "box": ParagraphStyle("box", parent=base, alignment=TA_CENTER),
        "company": ParagraphStyle(
            "company", parent=base, fontSize=8.5, leading=11, alignment=TA_CENTER
        ),
        "legal": ParagraphStyle(
            "legal", parent=base, fontName=ITALIC, fontSize=6.5, leading=8.4, textColor=primary
        ),
        "logo_text": ParagraphStyle(
            "logo_text", parent=base, fontName=MEDIUM, fontSize=15, leading=18,
            textColor=primary, alignment=2,
        ),
    }


def _value_cell(row: Row, styles: dict[str, ParagraphStyle]) -> list[Paragraph]:
    out: list[Paragraph] = []
    if row.text:
        out.append(Paragraph(_p(row.text), styles["value"]))
    for b in row.bullets:
        indent = 8 + 14 * b.level
        style = ParagraphStyle(
            f"bullet{b.level}", parent=styles["value"], leftIndent=indent, bulletIndent=indent - 7
        )
        out.append(Paragraph(_p(b.text), style, bulletText="•"))
    return out


def _boxed(text: str, styles: dict[str, ParagraphStyle], width: float) -> Table:
    box = Table([[Paragraph(_p(text), styles["box"])]], colWidths=[width])
    box.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.8, _RULE),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return box


def _logo(branding: Branding, styles: dict[str, ParagraphStyle]):
    """The logo scaled into 62 × 20 mm, or the company name in its place."""
    if branding.logo:
        reader = ImageReader(io.BytesIO(branding.logo))
        w, h = reader.getSize()
        scale = min(62 * mm / w, 20 * mm / h)
        return Image(io.BytesIO(branding.logo), width=w * scale, height=h * scale)
    if branding.company_name:
        return Paragraph(_p(branding.company_name), styles["logo_text"])
    return ""


def render(sheet: Sheet, branding: Branding) -> bytes:
    """The cover sheet as PDF bytes (A4, as many pages as the text needs)."""
    _register_fonts()
    primary = colors.HexColor(branding.primary_color)
    styles = _styles(primary)
    width = A4[0] - 2 * _MARGIN_X

    # The foot is drawn on every page, so its height decides the frame's
    # bottom margin: measured, not guessed, because the AGB text is the
    # agency's and may be three lines or eight.
    foot: list[Paragraph] = []
    if branding.company_line:
        foot.append(Paragraph(_p(branding.company_line), styles["company"]))
    if branding.legal_text:
        foot.append(Paragraph(_p(branding.legal_text), styles["legal"]))
    heights = [p.wrap(width, A4[1])[1] for p in foot]
    foot_height = sum(heights) + 5 * max(len(foot) - 1, 0)
    bottom = 12 * mm + foot_height + (8 * mm if foot else 0)

    def draw_foot(canvas, _doc) -> None:
        canvas.saveState()
        y = 12 * mm + foot_height
        for para, h in zip(foot, heights, strict=True):
            y -= h
            para.drawOn(canvas, _MARGIN_X, y)
            y -= 5
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=_MARGIN_X,
        rightMargin=_MARGIN_X,
        topMargin=_TOP,
        bottomMargin=bottom,
        title=sheet.title,
        author=branding.company_name or "",
        creator="Eligo Labs",
    )

    title = Paragraph(f"<u>{_p(sheet.title)}</u>", styles["title"])
    head = Table([[title, _logo(branding, styles)]], colWidths=[width - 66 * mm, 66 * mm])
    head.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    story: list = [head, Spacer(1, 10 * mm)]

    if sheet.position:
        story += [
            _boxed(f"Angestrebte Position: {sheet.position}", styles, width - 16 * mm),
            Spacer(1, 7 * mm),
        ]

    if sheet.rows:
        data = [
            [Paragraph(_p(f"{row.label}:"), styles["label"]), _value_cell(row, styles)]
            for row in sheet.rows
        ]
        # splitInRow: a Zusammenfassung longer than a page breaks inside its
        # row instead of failing the whole document.
        table = Table(data, colWidths=[_LABEL_WIDTH, width - _LABEL_WIDTH], splitInRow=1)
        table.setStyle(
            TableStyle(
                [
                    ("GRID", (0, 0), (-1, -1), 0.8, _RULE),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                    ("LEFTPADDING", (0, 0), (-1, -1), 7),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )
        story += [table, Spacer(1, 7 * mm)]

    if sheet.contact:
        story.append(_boxed(sheet.contact, styles, width - 12 * mm))

    doc.build(story, onFirstPage=draw_foot, onLaterPages=draw_foot)
    return buf.getvalue()
