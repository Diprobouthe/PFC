"""Read-only, batched data assembly for the live Tournament Overview.

The Overview is a spectator projection only. It does not participate in Match
activation, scoring, result validation, tournament progression, or roster
writes. It resolves P4 Mêlée players from MatchPlayer snapshots or the exact
MeleeRoundAssignment for each Match; permanent Player.team is only used for
legacy Matches with no assignment dataset, matching the established P3 resolver
precedence.
"""

from collections import defaultdict

from django.db.models import Q

from matches.models import LiveScoreboard, MatchPlayer
from practice.models import Shot
from tournaments.models import MeleeRoundAssignment


OVERVIEW_MATCH_STATUSES = ("active", "pending_verification")


def build_tournament_overview_cards(tournament):
    """Return cards and public current-end actions using batched queries only.

    The returned cards contain only existing match, scoreboard, roster, and
    already-permitted tracking information. No generated data is stored and no
    scoreboard state is changed. The second return value is a JSON-compatible
    ``{scoreboard_id: [actions...]}`` mapping for client-side feed rendering.
    """
    matches = list(
        tournament.matches.filter(status__in=OVERVIEW_MATCH_STATUSES)
        .select_related("team1", "team2", "round", "court")
        .order_by("round__number", "created_at", "id")
    )
    if not matches:
        return [], {}

    match_ids = [match.id for match in matches]
    scoreboards = {
        scoreboard.tournament_match_id: scoreboard
        for scoreboard in LiveScoreboard.objects.filter(
            tournament_match_id__in=match_ids,
        ).only(
            "id",
            "tournament_match_id",
            "team1_score",
            "team2_score",
            "is_active",
            "updated_at",
            "last_updated_by",
        )
    }

    # MatchPlayer is authoritative after a side has been activated. Fetch every
    # snapshot in one query; sides with no snapshot are resolved below from the
    # exact Mêlée Round assignment (or only then the historic legacy fallback).
    snapshots_by_match_team = defaultdict(list)
    snapshot_side_keys = set()
    for participant in (
        MatchPlayer.objects.filter(match_id__in=match_ids)
        .select_related("player")
        .order_by("player__name", "player_id")
    ):
        key = (participant.match_id, participant.team_id)
        snapshots_by_match_team[key].append(
            {
                "id": participant.player_id,
                "name": participant.player.name,
                "role": participant.get_role_display(),
            }
        )
        snapshot_side_keys.add(key)

    melee_round_keys = {
        (match.tournament_id, match.round_id)
        for match in matches
        if tournament.is_melee and match.round_id
    }
    assignments_by_round_team = defaultdict(list)
    assignment_round_keys = set()
    if melee_round_keys:
        assignment_filter = Q()
        for tournament_id, round_id in melee_round_keys:
            assignment_filter |= Q(tournament_id=tournament_id, round_id=round_id)
        for assignment in (
            MeleeRoundAssignment.objects.filter(assignment_filter)
            .select_related("player")
            .order_by("player__name", "player_id")
        ):
            assignment_round_keys.add((assignment.tournament_id, assignment.round_id))
            if (
                assignment.state == MeleeRoundAssignment.ASSIGNED
                and assignment.team_id
            ):
                assignments_by_round_team[
                    (assignment.tournament_id, assignment.round_id, assignment.team_id)
                ].append(
                    {
                        "id": assignment.player_id,
                        "name": assignment.player.name,
                        "role": "",
                    }
                )

    # The Player.team fallback exists only for true legacy Matches whose exact
    # Mêlée Round has no assignment rows at all. Query every needed Team once.
    legacy_team_ids = set()
    for match in matches:
        for team_id in (match.team1_id, match.team2_id):
            if not team_id or (match.id, team_id) in snapshot_side_keys:
                continue
            if (
                tournament.is_melee
                and match.round_id
                and (match.tournament_id, match.round_id) in assignment_round_keys
            ):
                continue
            legacy_team_ids.add(team_id)

    players_by_legacy_team = defaultdict(list)
    if legacy_team_ids:
        from teams.models import Player

        for player in Player.objects.filter(team_id__in=legacy_team_ids).order_by(
            "name", "id"
        ):
            players_by_legacy_team[player.team_id].append(
                {"id": player.id, "name": player.name, "role": ""}
            )

    cards = []
    scoreboard_by_id = {}
    side_by_match_player_id = {}
    for match in matches:
        scoreboard = scoreboards.get(match.id)
        if scoreboard:
            scoreboard_by_id[scoreboard.id] = scoreboard

        def players_for_side(team_id):
            snapshot_players = snapshots_by_match_team.get((match.id, team_id))
            if snapshot_players:
                return snapshot_players
            if (
                tournament.is_melee
                and match.round_id
                and (match.tournament_id, match.round_id) in assignment_round_keys
            ):
                return assignments_by_round_team.get(
                    (match.tournament_id, match.round_id, team_id), []
                )
            return players_by_legacy_team.get(team_id, [])

        team1_players = players_for_side(match.team1_id)
        team2_players = players_for_side(match.team2_id)
        for player in team1_players:
            side_by_match_player_id[(match.id, player["id"])] = "team1"
        for player in team2_players:
            side_by_match_player_id[(match.id, player["id"])] = "team2"

        cards.append(
            {
                "match_id": match.id,
                "scoreboard_id": scoreboard.id if scoreboard else None,
                "round_number": match.round.number if match.round_id else None,
                "court_label": str(match.court) if match.court_id else "",
                "waiting_for_court": bool(match.waiting_for_court),
                "status": match.status,
                "team1_name": match.team1.name if match.team1_id else "Team 1",
                "team2_name": match.team2.name if match.team2_id else "Team 2",
                "team1_players": team1_players,
                "team2_players": team2_players,
                "team1_score": scoreboard.team1_score if scoreboard else 0,
                "team2_score": scoreboard.team2_score if scoreboard else 0,
                "scoreboard_active": bool(scoreboard and scoreboard.is_active),
            }
        )

    return cards, _current_end_actions_by_scoreboard(
        scoreboard_by_id,
        matches,
        side_by_match_player_id,
    )


def _current_end_actions_by_scoreboard(
    scoreboard_by_id,
    matches,
    side_by_match_player_id,
):
    """Batch the existing public tracking projection for all Overview cards."""
    if not scoreboard_by_id:
        return {}

    from match_tracking.models import MatchTrackingSession, TrackingAuthorization

    match_by_id = {match.id: match for match in matches}
    scoreboard_ids_by_match_id = {
        scoreboard.tournament_match_id: scoreboard_id
        for scoreboard_id, scoreboard in scoreboard_by_id.items()
    }
    match_ids = list(scoreboard_ids_by_match_id)

    tracking_sessions = list(
        MatchTrackingSession.objects.filter(
            match_type="match",
            match_pk__in=match_ids,
            status=MatchTrackingSession.STATUS_ACTIVE,
        ).order_by("match_pk", "-started_at", "-id")
    )
    active_session_by_match_id = {}
    for session in tracking_sessions:
        active_session_by_match_id.setdefault(session.match_pk, session)
    if not active_session_by_match_id:
        return {scoreboard_id: [] for scoreboard_id in scoreboard_by_id}

    session_ids = [session.id for session in active_session_by_match_id.values()]
    permitted_player_ids_by_session = defaultdict(set)
    for authorization in TrackingAuthorization.objects.filter(
        tracking_session_id__in=session_ids,
        is_active=True,
        broadcast_permitted=True,
    ).values("tracking_session_id", "player_id"):
        permitted_player_ids_by_session[authorization["tracking_session_id"]].add(
            authorization["player_id"]
        )

    latest_score_timestamp_by_scoreboard = {}
    from matches.models import ScoreUpdate

    for update in (
        ScoreUpdate.objects.filter(scoreboard_id__in=scoreboard_by_id)
        .order_by("scoreboard_id", "-timestamp", "-id")
        .only("scoreboard_id", "timestamp")
    ):
        latest_score_timestamp_by_scoreboard.setdefault(
            update.scoreboard_id, update.timestamp
        )

    shot_filter = Q()
    session_context = {}
    for match_id, session in active_session_by_match_id.items():
        scoreboard_id = scoreboard_ids_by_match_id.get(match_id)
        permitted_player_ids = permitted_player_ids_by_session.get(session.id, set())
        if not scoreboard_id or not permitted_player_ids:
            continue
        boundary = latest_score_timestamp_by_scoreboard.get(scoreboard_id) or session.started_at
        shot_filter |= Q(
            session__match_tracking_link__tracking_session_id=session.id,
            session__match_tracking_link__player_id__in=permitted_player_ids,
            timestamp__gt=boundary,
        )
        session_context[session.id] = (scoreboard_id, match_by_id[match_id])

    actions_by_scoreboard = {
        scoreboard_id: [] for scoreboard_id in scoreboard_by_id
    }
    if not session_context:
        return actions_by_scoreboard

    for shot in (
        Shot.objects.filter(shot_filter)
        .select_related("session__match_tracking_link__player")
        .order_by("timestamp", "id")
    ):
        link = shot.session.match_tracking_link
        context = session_context.get(link.tracking_session_id)
        if context is None:
            continue
        scoreboard_id, match = context
        actions_by_scoreboard[scoreboard_id].append(
            {
                "id": str(shot.id),
                "player_name": link.player.name,
                "outcome": shot.outcome,
                "side": side_by_match_player_id.get((match.id, link.player_id)),
            }
        )

    # Fail closed: only the same existing public feed sides are rendered.
    for scoreboard_id, actions in actions_by_scoreboard.items():
        actions_by_scoreboard[scoreboard_id] = [
            action for action in actions if action["side"] in ("team1", "team2")
        ]
    return actions_by_scoreboard
