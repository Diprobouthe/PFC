"""A4 tournament-wide VS report; all values are read from canonical match records.

No GET writes, no unpublished lineup disclosure, no simulated referee signature.
Uses the same PFC PDF primitives as historical Match Analysis exports.
"""
from io import BytesIO
from itertools import groupby

from django.http import HttpResponse
from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Spacer, KeepTogether

from matches.models import Match
from tournaments.vs_utils import get_vs_rankings, get_vs_points_for_match_type
from pfc_core.pdf_reporting import header, heading, table, text, page_footer


def _format_match_type(match):
    return {
        "tete_a_tete": "Tête-à-tête",
        "doublet": "Doublettes",
        "triplet": "Triplettes",
    }.get(match.match_type, "Δεν ορίστηκε")


def _match_row(match):
    status_labels = {
        "completed": "Επικυρωμένο",
        "waiting_validation": "Προς επικύρωση",
        "active": "Σε εξέλιξη",
        "pending": "Αναμονή",
        "pending_verification": "Αναμονή γηπέδου",
        "cancelled": "Ακυρωμένο",
    }

    # Public PDF: NO player identities before BOTH captains lock their lineups.
    roster1 = roster2 = "—"
    if match.vs_lineup_team1_locked and match.vs_lineup_team2_locked:
        by_team = {
            lineup.team_id: ", ".join(player.name for player in lineup.players.all())
            for lineup in match.vs_lineups.all() if lineup.is_locked
        }
        roster1 = by_team.get(match.team1_id) or "—"
        roster2 = by_team.get(match.team2_id) or "—"

    lineups = (
        f"{match.team1.name} ({roster1}) / "
        f"{match.team2.name} ({roster2})"
    )
    confirmed = match.status == "completed"
    score = (
        f"{match.team1_score} – {match.team2_score}"
        if confirmed and match.team1_score is not None and match.team2_score is not None
        else "—"
    )
    value = match.vs_points_value
    if value is None:
        value = get_vs_points_for_match_type(match.match_type) or 0
    if confirmed and match.winner_id == match.team1_id:
        points = f"{value} – 0"
    elif confirmed and match.winner_id == match.team2_id:
        points = f"0 – {value}"
    else:
        points = "—"
    return [
        str(match.id), _format_match_type(match), lineups,
        score, points, status_labels.get(match.status, match.status),
    ]


def render_vs_tournament_report(tournament):
    """Return downloadable tournament-level PDF for any VS competition state."""
    matches = list(
        Match.objects.filter(tournament=tournament, vs_encounter__isnull=False)
        .select_related("team1", "team2", "vs_encounter")
        .prefetch_related("vs_lineups__players")
        .order_by("vs_encounter_id", "pk")
    )
    completed_count = sum(match.status == "completed" for match in matches)
    final = bool(matches and not tournament.is_active and completed_count == len(matches))
    report_type = "ΤΕΛΙΚΟ" if final else "ΠΡΟΣΩΡΙΝΟ"
    exported = timezone.localtime().strftime("%d/%m/%Y %H:%M")

    buff = BytesIO()
    doc = SimpleDocTemplate(
        buff, pagesize=A4, leftMargin=15*mm, rightMargin=15*mm,
        topMargin=13*mm, bottomMargin=18*mm,
        title=f"PFC VS - {tournament.name}",
        author="PFC",
    )
    story = header(
        "Φύλλο διοργάνωσης VS",
        f"{tournament.name} | {report_type} | Εξαγωγή: {exported}",
    )
    story += [
        text(f"Επικυρωμένα παιχνίδια: {completed_count}/{len(matches)}. "
             "Η κατάταξη βασίζεται αποκλειστικά σε επικυρωμένα αποτελέσματα."),
        heading("Συγκεντρωτική κατάταξη"),
    ]

    standings = get_vs_rankings(tournament)
    stand_rows = [["Θέση", "Ομάδα", "Αγ.", "Νίκες", "Ήττες", "VS βαθμοί", "Σκορ +/−"]]
    for entry in standings:
        stand_rows.append([
            entry["position"], entry["team"].name, entry["matches_played"],
            entry["matches_won"], entry["matches_lost"], entry["vs_points"],
            f'{entry["points_scored"]} / {entry["points_conceded"]}',
        ])
    if len(stand_rows) == 1:
        story.append(text("Δεν υπάρχουν ακόμη εγγεγραμμένες ομάδες."))
    else:
        story.append(table(stand_rows, [14*mm, 55*mm, 14*mm, 17*mm, 17*mm, 29*mm, 34*mm]))
        story.append(text("VS: νίκη tête-à-tête 2 βαθμοί, doublettes 3, triplettes 5. "
                          "Σε ισοβαθμία δεν αποδίδεται επίσημο tie-break από αυτή την εξαγωγή.", size=7))
    story.append(Spacer(1, 4*mm))

    story.append(heading("Αναλυτικά αποτελέσματα διοργάνωσης"))
    if matches:
        for encounter_id, encounter_games in groupby(matches, key=lambda match: match.vs_encounter_id):
            games = list(encounter_games)
            first = games[0]
            story.append(heading(f"{first.team1.name} – {first.team2.name}", size=10))
            rows = [["ID", "Μορφή", "Ομάδες / συνθέσεις", "Σκορ", "VS", "Κατάσταση"]]
            rows.extend(_match_row(match) for match in games)
            story.append(table(rows, [10*mm, 24*mm, 76*mm, 21*mm, 16*mm, 33*mm]))
            # Only confirmed results count toward this summary.
            points1 = points2 = 0
            for match in games:
                if match.status != "completed":
                    continue
                value = match.vs_points_value
                if value is None:
                    value = get_vs_points_for_match_type(match.match_type) or 0
                if match.winner_id == match.team1_id:
                    points1 += value
                elif match.winner_id == match.team2_id:
                    points2 += value
            story.append(text(
                f"Επικυρωμένοι VS βαθμοί: {first.team1.name} {points1} – "
                f"{points2} {first.team2.name}", size=8,
            ))
            story.append(Spacer(1, 3*mm))
    else:
        story.append(text("Δεν έχουν δημιουργηθεί ακόμη παιχνίδια."))

    story.append(heading("Παρατηρήσεις διοργάνωσης", size=11))
    if tournament.report_notes.strip():
        story.append(text(tournament.report_notes.strip()))
    else:
        story.append(text("________________________________________________________"))
        story.append(text("________________________________________________________"))
        story.append(text("________________________________________________________"))

    story.append(Spacer(1, 7*mm))
    story.append(KeepTogether([
        text("Αυτόματη καταγραφή: πεταχύUMP / PFC. "
             "Δεν αποτελεί πιστοποιημένη υπογραφή φυσικού διαιτητή.", size=8),
        text("Διαιτητής (όταν υπάρχει): __________________________", size=9),
        Spacer(1, 5*mm),
        text("Υπογραφή: ____________________     Ημερομηνία: ____________________", size=9),
    ]))
    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    buff.seek(0)
    response = HttpResponse(buff.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="PFC_VS_Tournament_{tournament.pk}.pdf"'
    )
    return response
