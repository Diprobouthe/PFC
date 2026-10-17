"""Compact tournament-wide VS match sheet, from canonical recorded results.

A match sheet is organized by game format, with both opposing lineups side by
side. Unconfirmed scores are never passed off as final, and lineups are hidden
until both captains have locked them. GET is read-only.
"""
from collections import defaultdict

from django.db.models import Q
from io import BytesIO

from django.http import HttpResponse
from django.utils import timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Spacer

from matches.models import Match
from pfc_core.pdf_reporting import header, heading, page_footer, table, text
from tournaments.vs_utils import get_vs_points_for_match_type, get_vs_rankings


FORMATS = (
    ("tete_a_tete", "ΜΟΝΑ", "Tête-à-tête"),
    ("doublet", "ΔΙΠΛΑ", "Doublettes"),
    ("triplet", "ΤΡΙΠΛΑ", "Triplettes"),
)

STATUS_LABELS = {
    "completed": "Επικυρωμένο",
    "waiting_validation": "Προς επικύρωση",
    "active": "Σε εξέλιξη",
    "pending": "Αναμονή",
    "pending_verification": "Αναμονή γηπέδου",
    "cancelled": "Ακυρωμένο",
}


def _player_names(match, team_id):
    """Use the historical MatchPlayer snapshot as canonical completed roster.

    Before VS route restoration, some pending games acquired provisional
    VSLineup records without starting. Once a real Match is completed its
    MatchPlayer entries supersede *all* provisional lineup data for printing.
    Preserve the VSLineup fallback only for older validated games with no
    MatchPlayer snapshot; never show partial/unvalidated rosters.
    """
    if match.status != "completed" and not (
        match.vs_lineup_team1_locked and match.vs_lineup_team2_locked
    ):
        return "Σύνθεση σε αναμονή"

    if match.status == "completed":
        players = [
            row.player.name for row in match.match_players.all()
            if row.team_id == team_id
        ]
        if players:
            return "\n".join(players)

    for lineup in match.vs_lineups.all():
        if lineup.team_id == team_id and (lineup.is_locked or match.status == "completed"):
            names = [player.name for player in lineup.players.all()]
            if names:
                return "\n".join(names)
    return "Δεν καταγράφηκε σύνθεση"


def _match_row(match, *, show_team_names=False):
    """The two opposing player columns are the core of the printable sheet."""
    first = _player_names(match, match.team1_id)
    second = _player_names(match, match.team2_id)
    if show_team_names:
        first = f"{match.team1.name}\n{first}"
        second = f"{match.team2.name}\n{second}"

    if match.status == "completed" and None not in (match.team1_score, match.team2_score):
        score = f"{match.team1_score} – {match.team2_score}"
        value = match.vs_points_value
        if value is None:
            value = get_vs_points_for_match_type(match.match_type) or 0
        if match.winner_id == match.team1_id:
            vs = f"{value} – 0"
        elif match.winner_id == match.team2_id:
            vs = f"0 – {value}"
        else:
            vs = "—"
    else:
        score = "—"
        vs = "—"

    return [
        f"#{match.pk}", first, score, second, vs,
        STATUS_LABELS.get(match.status, match.status),
    ]


def vs_sheet_ready(tournament):
    """Only an entirely validated VS encounter can have an official match sheet.

    The underlying match status is canonical. In particular, a tournament may
    still be marked active after every VS game has finished; that flag must
    not delay the sheet. Empty encounters and missing formats/scores never
    count as completed games.
    """
    from tournaments.models import VSEncounter

    encounters = VSEncounter.objects.filter(tournament=tournament)
    if not encounters.exists():
        return False

    games = Match.objects.filter(tournament=tournament, vs_encounter__tournament=tournament)
    if not games.exists():
        return False
    if games.values("vs_encounter_id").distinct().count() != encounters.count():
        return False
    incomplete = games.exclude(status="completed") | games.filter(
        Q(match_type__isnull=True) | Q(team1_score__isnull=True) | Q(team2_score__isnull=True)
    ) | games.exclude(match_type__in=[key for key, _, _ in FORMATS])
    return not incomplete.exists()


def render_vs_tournament_report(tournament):
    """Build a final, compact match sheet, only after all VS games complete."""
    if not vs_sheet_ready(tournament):
        raise ValueError("VS match sheet cannot be generated before all games are validated.")
    matches = list(
        Match.objects.filter(tournament=tournament, vs_encounter__isnull=False)
        .select_related("team1", "team2", "vs_encounter")
        .prefetch_related("vs_lineups__players", "match_players__player")
        .order_by("vs_encounter_id", "pk")
    )
    pairs = {
        (match.vs_encounter.team1_id, match.vs_encounter.team2_id):
        (match.vs_encounter.team1, match.vs_encounter.team2)
        for match in matches
    }
    unique_pair = next(iter(pairs.values())) if len(pairs) == 1 else None
    # Preserve the two opposite columns even for a tournament with more than
    # one encounter; in that case each row labels its own team.
    show_team_names = unique_pair is None
    completed_count = sum(match.status == "completed" for match in matches)
    label = "ΤΕΛΙΚΟ"

    buff = BytesIO()
    doc = SimpleDocTemplate(
        buff, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=11 * mm, bottomMargin=16 * mm,
        title=f"PFC VS | {tournament.name}", author="PFC",
    )
    story = header(
        "Φύλλο αγώνα VS",
        f"{tournament.name} | {label} | {timezone.localtime().strftime('%d/%m/%Y %H:%M')}",
    )

    if unique_pair:
        a, b = unique_pair
        story.append(table(
            [["ΟΜΑΔΑ Α", "ΟΜΑΔΑ Β"], [a.name, b.name]],
            [90 * mm, 90 * mm],
        ))
        story.append(Spacer(1, 3 * mm))
    elif pairs:
        story.append(text(f"Αναμετρήσεις: {len(pairs)}. Οι ομάδες αναγράφονται ανά παιχνίδι.", size=8))

    story.append(text(
        f"Επικυρωμένα παιχνίδια: {completed_count}/{len(matches)}  |  "
        f"Ημερομηνία: {timezone.localtime(tournament.start_date).strftime('%d/%m/%Y')}.  "
        "Μόνο τα επικυρωμένα αποτελέσματα μετρούν στη βαθμολογία.", size=8,
    ))

    groups = defaultdict(list)
    for match in matches:
        groups[match.match_type or "unassigned"].append(match)

    for format_key, greek, international in FORMATS:
        games = groups.pop(format_key, [])
        if not games:
            continue
        story.append(heading(f"{greek}  /  {international}   ·   {len(games)} παιχνίδια", size=10))
        rows = [["#", "Παίκτες Α", "Σκορ", "Παίκτες Β", "VS", "Κατάσταση"]]
        rows.extend(_match_row(game, show_team_names=show_team_names) for game in games)
        story.append(table(rows, [12*mm, 55*mm, 24*mm, 55*mm, 15*mm, 19*mm]))
        story.append(Spacer(1, 2 * mm))

    # The readiness guard excludes all undefined formats and unvalidated games.
    assert not groups, "Validated VS game has an unexpected format"

    # Source of truth: canonical rankings from completed Match rows.
    # This is not a cached leaderboard projection.
    standings = get_vs_rankings(tournament)
    category_points = defaultdict(lambda: defaultdict(int))
    for match in matches:
        if match.status != "completed" or not match.winner_id:
            continue
        value = match.vs_points_value
        if value is None:
            value = get_vs_points_for_match_type(match.match_type) or 0
        category_points[match.winner_id][match.match_type] += value

    story.append(heading("ΣΥΓΚΕΝΤΡΩΤΙΚΟ ΑΠΟΤΕΛΕΣΜΑ", size=10))
    rows = [["Θέση", "Ομάδα", "Μονά VS", "Διπλά VS", "Τριπλά VS", "Σύνολο VS", "Νίκες"]]
    for entry in standings:
        t = entry["team"]
        points = category_points[t.pk]
        rows.append([
            entry["position"], t.name,
            points["tete_a_tete"], points["doublet"], points["triplet"],
            entry["vs_points"], entry["matches_won"],
        ])
    if standings:
        story.append(table(rows, [13*mm, 53*mm, 21*mm, 21*mm, 21*mm, 29*mm, 22*mm]))
    else:
        story.append(text("Δεν υπάρχουν ακόμη εγγεγραμμένες ομάδες."))
    story.append(text(
        "Βαθμοί νίκης VS: μονά 2 · διπλά 3 · τριπλά 5. "
        "Σε ισοβαθμία δεν εφαρμόζεται εδώ επιπλέον κριτήριο.", size=7,
    ))

    story.append(heading("ΠΑΡΑΤΗΡΗΣΕΙΣ", size=10))
    if tournament.report_notes.strip():
        story.append(text(tournament.report_notes.strip(), size=8))
    else:
        story.append(text("Δεν καταχωρίστηκαν παρατηρήσεις.", size=8))

    story.append(heading("ΨΗΦΙΑΚΗ ΕΠΙΚΥΡΩΣΗ ΦΥΛΛΟΥ", size=10))
    if unique_pair:
        encounter = matches[0].vs_encounter
        attestations = {
            row.role: row for row in encounter.sheet_attestations.all()
        }
        required = [
            ("team1", f"Ομάδα Α · {encounter.team1.name}"),
            ("team2", f"Ομάδα Β · {encounter.team2.name}"),
        ]
        if encounter.sheet_referee_required:
            required.append(("referee", "Διαιτητής (δήλωση QR · χωρίς πιστοποίηση)"))
        for role, title in required:
            row = attestations.get(role)
            if row is not None:
                timestamp = timezone.localtime(row.attested_at).strftime("%d/%m/%Y %H:%M")
                story.append(text(
                    f"{title}: {row.player_name} · Επικυρώθηκε μέσω PFC QR · {timestamp}",
                    size=8,
                ))
                story.append(text(
                    f"Παρατήρηση: {row.remarks or 'Όλα καλώς'}", size=8,
                ))
    story.append(Spacer(1, 2 * mm))
    story.append(text(
        "πετΑ UMP / PFC · Ψηφιακή καταγραφή ανάληψης ευθύνης μέσω καρτών QR. "
        "Δεν αποτελεί πιστοποιημένη ηλεκτρονική υπογραφή ή πιστοποίηση διαιτητή.",
        size=7,
    ))
    doc.build(story, onFirstPage=page_footer, onLaterPages=page_footer)
    buff.seek(0)
    response = HttpResponse(buff.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = (
        f'attachment; filename="PFC_VS_Tournament_{tournament.pk}.pdf"'
    )
    return response
