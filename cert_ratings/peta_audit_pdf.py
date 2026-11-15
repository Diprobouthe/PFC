"""Read-only, post-settlement PETA audit PDF from persisted event snapshots."""
from io import BytesIO

from django.http import Http404, HttpResponse
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Spacer

from cert_ratings.peta_models import PetaEvent, PetaEventEntry
from pfc_core.pdf_reporting import header, heading, page_footer, table, text


def peta_audit_pdf(tournament_id):
    event = PetaEvent.objects.select_related("series", "tournament").filter(
        tournament_id=tournament_id, settled_at__isnull=False
    ).first()
    if event is None:
        raise Http404("PETA audit is available only after settlement.")

    audit = event.settlement_audit or {}
    entries = list(PetaEventEntry.objects.filter(event=event)
                   .select_related("player").order_by("player__name", "player_id"))
    previous = {}
    prior_events = PetaEvent.objects.filter(
        series=event.series, ordinal__lt=event.ordinal,
        settled_at__isnull=False,
    ).order_by("-ordinal")
    for prior in prior_events:
        for entry in PetaEventEntry.objects.filter(event=prior).only("player_id", "end_rating"):
            if entry.player_id not in previous and entry.end_rating is not None:
                previous[entry.player_id] = entry.end_rating

    def fmt(value):
        return "—" if value is None else f"{float(value):.2f}"

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=14 * mm,
                            leftMargin=14 * mm, topMargin=14 * mm, bottomMargin=18 * mm)
    story = header("PETA Event Audit", f"{event.series.name} | Event {event.ordinal}/8 | {event.tournament.name}")
    story.append(text(f"Finalized: {event.settled_at:%Y-%m-%d %H:%M} UTC | Tournament #{tournament_id}"))
    story.append(text("Certified PETA ratings are separate from global PFC ratings. "
                      "For returning players the previous PETA end rating is the protected entry rating. "
                      "The global PFC rating at roster freeze is not historically stored in this report."))
    story.append(heading("Event settlement"))
    story.append(table([
        ["Pool", "Distributed", "Undistributed"],
        [fmt(audit.get("pool")), fmt(audit.get("distributed")), fmt(audit.get("undistributed"))],
    ], [60 * mm] * 3))
    story.append(Spacer(1, 5 * mm))
    story.append(heading("Player rating and Travel Points audit"))
    story.append(table([
        ["Player", "Prior PETA", "Entry", "End", "Delta", "Personal", "Dividend", "Total TP"],
        *[
            [
                entry.player.name, fmt(previous.get(entry.player_id)),
                fmt(entry.entry_rating), fmt(entry.end_rating),
                fmt(entry.end_rating - entry.entry_rating) if entry.end_rating is not None else "—",
                fmt(entry.personal_earnings), fmt(entry.dividend),
                fmt(audit.get("travel_points_after", {}).get(str(entry.player_id))),
            ]
            for entry in entries
        ],
    ], [37 * mm, 21 * mm, 18 * mm, 18 * mm, 18 * mm, 22 * mm, 22 * mm, 24 * mm]))
    story.append(Spacer(1, 5 * mm))
    story.append(heading("Dividend eligibility and awards"))
    story.append(text("Eligible means at least one valid Live Score update or tracked shot in EVERY completed "
                      "match played, with no confirmed dividend suspension. Missing one match means not eligible. "
                      "This is an eligibility result, not a finding of misconduct."))
    awards = audit.get("awards", {})
    story.append(table([
        ["Player", "Eligibility", "Keep All", "Awards (pool contributions)"],
        *[
            [
                entry.player.name,
                "Eligible" if entry.eligible_for_dividend is True else (
                    "Not eligible" if entry.eligible_for_dividend is False else "Not assessed"),
                "Yes" if entry.use_exception else "No",
                ", ".join(f"{key}: {value}" for key, value in
                          awards.get(str(entry.player_id), {}).items()) or "None",
            ]
            for entry in entries
        ],
    ], [42 * mm, 35 * mm, 23 * mm, 80 * mm]))
    story.append(Spacer(1, 4 * mm))
    story.append(text("All values above are read from finalized event entries and the stored settlement audit; "
                      "this report does not recalculate points or alter results. "
                      "The awards shown are pool contributions, not necessarily personal credits."))
    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="PETA_Event_{event.ordinal}_Audit.pdf"'
    return response
