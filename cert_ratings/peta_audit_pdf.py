"""One-page, read-only PETA event audit from settled results."""
from io import BytesIO
from pathlib import Path

from django.http import Http404, HttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

from cert_ratings.peta_models import PetaEvent, PetaEventEntry, PetaCompetitor
from cert_ratings.peta_service import _contributing_player_ids
from tournaments.partnership_models import MeleePlayerStats
from tournaments.rating_history_utils import get_player_rating_at_time

FONT_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
FONT_BOLD_PATH = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def _fonts():
    if FONT_PATH.exists() and FONT_BOLD_PATH.exists():
        if "PetaAudit" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("PetaAudit", str(FONT_PATH)))
            pdfmetrics.registerFont(TTFont("PetaAuditBold", str(FONT_BOLD_PATH)))
        return "PetaAudit", "PetaAuditBold"
    return "Helvetica", "Helvetica-Bold"


def _fmt(value):
    return "—" if value is None else f"{float(value):.2f}"


def peta_audit_pdf(request, tournament_id):
    event = PetaEvent.objects.select_related("series", "tournament").filter(
        tournament_id=tournament_id, settled_at__isnull=False
    ).first()
    if event is None:
        raise Http404("PETA audit is available only after settlement.")

    audit = event.settlement_audit or {}
    entries = list(PetaEventEntry.objects.filter(event=event)
                   .select_related("player").order_by("player__name", "player_id"))
    stats = {s.player_id: s for s in MeleePlayerStats.objects.filter(
        tournament=event.tournament, player_id__in=[e.player_id for e in entries])}
    previous_event = PetaEvent.objects.filter(
        series=event.series, ordinal__lt=event.ordinal,
        settled_at__isnull=False,
    ).order_by("-ordinal").first()

    # This is a diagnostic, not a punitive action. Compare PFC after the
    # previous event to the current event's saved starting PFC rating.
    # Do not substitute a current global PFC rating for historical snapshots.
    # For Helpful, recompute only the actual recorded contributions, independently
    # of any administrative dividend suspension.
    contributors = _contributing_player_ids(event.tournament, [e.player_id for e in entries])
    suspended = dict(PetaCompetitor.objects.filter(
        series=event.series, player_id__in=[e.player_id for e in entries]
    ).values_list("player_id", "dividend_suspended"))

    buffer = BytesIO()
    page_w, page_h = landscape(A4)
    pdf = Canvas(buffer, pagesize=(page_w, page_h))
    regular, bold = _fonts()
    navy = colors.HexColor("#17243A")
    muted = colors.HexColor("#627184")
    green = colors.HexColor("#168153")
    red = colors.HexColor("#B9383D")
    amber = colors.HexColor("#AE6A11")
    pdf.setFillColor(navy)
    pdf.setFont(bold, 17)
    pdf.drawString(27, page_h - 37, "PETA  |  EVENT AUDIT")
    pdf.setFont(regular, 9)
    pdf.setFillColor(muted)
    pdf.drawString(27, page_h - 54, f"{event.series.name}   •   Event {event.ordinal}/8   •   {event.tournament.name}")
    pdf.drawString(27, page_h - 69, f"Finalized {event.settled_at:%Y-%m-%d %H:%M} UTC   |   Tournament #{tournament_id}")
    pdf.setFont(bold, 9)
    pdf.setFillColor(navy)
    pdf.drawString(27, page_h - 89, "Travel Points pool")
    pdf.setFont(regular, 9)
    pdf.drawString(134, page_h - 89,
                   f"{_fmt(audit.get('pool'))}   |   Paid {_fmt(audit.get('distributed'))}   |   Unallocated {_fmt(audit.get('undistributed'))}")

    columns = [
        ("PLAYER", 27), ("PFC START → END", 211), ("PETA ENTRY → END", 342),
        ("TP +", 482), ("TOTAL TP", 552), ("PFC DROP", 641),
        ("HELPFUL", 724), ("DIVIDEND", 781),
    ]
    top = page_h - 111
    pdf.setFillColor(navy)
    pdf.roundRect(25, top - 24, page_w - 50, 25, 5, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont(bold, 7.2)
    for label, x in columns:
        pdf.drawString(x, top - 16, label)

    available = top - 39 - 47
    row_h = min(18.5, available / max(len(entries), 1))
    font_size = 8 if row_h >= 15 else 7
    y = top - 37
    for index, entry in enumerate(entries):
        if index % 2 == 0:
            pdf.setFillColor(colors.HexColor("#F2F5F8"))
            pdf.rect(25, y - row_h + 3, page_w - 50, row_h, fill=1, stroke=0)
        pdf.setFillColor(navy)
        pdf.setFont(regular, font_size)
        name = entry.player.name
        while pdfmetrics.stringWidth(name, regular, font_size) > 174 and len(name) > 4:
            name = name[:-2] + "…"
        pdf.drawString(27, y - row_h + 8, name)

        start = stats.get(entry.player_id)
        start_value = start.starting_rating if start is not None else None
        end_value = get_player_rating_at_time(entry.player, event.settled_at) if start is not None else None
        pdf.drawString(211, y - row_h + 8, f"{_fmt(start_value)} → {_fmt(end_value)}")
        pdf.drawString(342, y - row_h + 8, f"{_fmt(entry.entry_rating)} → {_fmt(entry.end_rating)}")
        pdf.drawString(482, y - row_h + 8, _fmt(entry.personal_earnings + entry.dividend))
        pdf.drawString(552, y - row_h + 8, _fmt(audit.get("travel_points_after", {}).get(str(entry.player_id))))

        drop = None
        if previous_event is not None and start_value is not None:
            prev_pfc = get_player_rating_at_time(entry.player, previous_event.settled_at)
            drop = float(prev_pfc) - float(start_value)
        if drop is None:
            alert, color = "—", muted
        elif drop >= 20:
            alert, color = f"RED {drop:.1f}", red
        elif drop >= 10:
            alert, color = f"WARN {drop:.1f}", amber
        else:
            alert, color = "—", muted
        pdf.setFillColor(color)
        pdf.drawString(641, y - row_h + 8, alert)

        helpful = entry.player_id in contributors
        pdf.setFillColor(green if helpful else red)
        pdf.drawString(724, y - row_h + 8, "✓" if helpful else "✕")
        eligible = entry.eligible_for_dividend
        pdf.setFillColor(green if eligible is True else red if eligible is False else muted)
        pdf.drawString(781, y - row_h + 8, "✓" if eligible is True else "✕" if eligible is False else "—")
        y -= row_h

    pdf.setFillColor(muted)
    pdf.setFont(regular, 7.1)
    pdf.drawString(27, 38, "Helpful: valid Live Score update or tracked shot in EVERY completed match played.")
    pdf.drawString(27, 27, "PFC drop: previous event settlement → current event start; WARN 10–<20, RED ≥20. A warning is not a penalty.")
    if any(suspended.values()):
        pdf.setFillColor(red)
        pdf.drawRightString(page_w - 27, 38, "Note: administrative dividend suspension exists.")
    pdf.setFillColor(muted)
    pdf.drawRightString(page_w - 27, 17, "PETA and PFC are separate ratings • Stored settlement values")
    pdf.save()
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="PETA_Event_{event.ordinal}_Audit.pdf"'
    return response
