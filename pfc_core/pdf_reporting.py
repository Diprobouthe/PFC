"""Common PFC PDF presentation helpers, shared by match and tournament reports.

ReportLab PDFs embed a Unicode font (bundled with already-installed matplotlib)
and the actual PFC SVG mark. Do not rely on PDF's built-in Helvetica for Greek.
"""
from functools import lru_cache
from html import escape
from pathlib import Path

from django.conf import settings
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, Table, TableStyle, Spacer


BLUE = colors.HexColor("#194C88")
PALE = colors.HexColor("#F4F7FA")
BORDER = colors.HexColor("#DCE3EA")


@lru_cache(maxsize=1)
def font_names():
    from matplotlib import get_data_path

    fonts = Path(get_data_path()) / "fonts" / "ttf"
    for name, filename in (
        ("PFC-DejaVu", "DejaVuSans.ttf"),
        ("PFC-DejaVu-Bold", "DejaVuSans-Bold.ttf"),
    ):
        pdfmetrics.registerFont(TTFont(name, str(fonts / filename)))
    pdfmetrics.registerFontFamily(
        "PFC-DejaVu",
        normal="PFC-DejaVu",
        bold="PFC-DejaVu-Bold",
    )
    return "PFC-DejaVu", "PFC-DejaVu-Bold"


def text(value, style=None, size=8):
    regular, _ = font_names()
    if style is None:
        style = ParagraphStyle(
            "PFCBody", fontName=regular, fontSize=size, leading=size * 1.42,
            alignment=TA_LEFT, textColor=colors.HexColor("#283543"),
            spaceAfter=3,
        )
    return Paragraph(escape(str(value if value is not None else "—")).replace("\n", "<br/>"), style)


def heading(label, size=13):
    _, bold = font_names()
    return text(label, ParagraphStyle(
        "PFCHeading", fontName=bold, fontSize=size,
        leading=size * 1.4, textColor=BLUE,
        spaceBefore=7, spaceAfter=7,
    ))


def table(rows, widths, header=True):
    regular, bold = font_names()
    wrapped = [[text(cell, ParagraphStyle(
        f"PFCcell{row_index}_{column_index}",
        fontName=bold if row_index == 0 and header else regular,
        fontSize=7.5 if row_index else 7.7,
        leading=10.4,
        textColor=colors.white if row_index == 0 and header else colors.HexColor("#283543"),
    )) for column_index, cell in enumerate(row)] for row_index, row in enumerate(rows)]
    result = Table(wrapped, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    rules = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, -1), (-1, -1), 0.4, BORDER),
    ]
    if header:
        rules += [
            ("BACKGROUND", (0, 0), (-1, 0), BLUE),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, PALE]),
        ]
    else:
        rules += [("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, PALE])]
    result.setStyle(TableStyle(rules))
    return result


def header(title, subtitle):
    """Use the actual static SVG logo (no baked-in raster or imitation)."""
    from svglib.svglib import svg2rlg

    logo_path = Path(settings.BASE_DIR) / "static" / "pfcLOGO.svg"
    logo = svg2rlg(str(logo_path))
    if logo is None:
        raise ValueError("Could not load PFC SVG logo")
    scale = (17 * mm) / max(logo.width, logo.height)
    logo.scale(scale, scale)
    logo.width *= scale
    logo.height *= scale
    title_block = [heading(title, size=15), text(subtitle, size=8)]
    header_table = Table([[logo, title_block]], colWidths=[22 * mm, 158 * mm])
    header_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
        ("LINEBELOW", (0, 0), (-1, -1), 1, BLUE),
    ]))
    return [header_table, Spacer(1, 5 * mm)]


def page_footer(canvas, document):
    font, _ = font_names()
    canvas.saveState()
    canvas.setFont(font, 8)
    canvas.setFillColor(colors.grey)
    canvas.drawRightString(195 * mm, 11 * mm, f"PFC | {document.page}")
    canvas.restoreState()
