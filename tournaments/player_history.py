"""Permanent, activation-onward Player tournament history and achievements.

This module is deliberately a projection of immutable Match/participant data. It
never assigns results, modifies Tournament progression, or resolves historical
rosters through the mutable ``Player.team`` affiliation.
"""

from collections import defaultdict
from decimal import Decimal

from django.db import models, transaction


MEDAL_METADATA = {
    "gold": ("medal_gold", "🥇", "Gold medal"),
    "silver": ("medal_silver", "🥈", "Silver medal"),
    "bronze": ("medal_bronze", "🥉", "Bronze medal"),
}
MELEE_AWARD_TYPES = {
    "winner": "most_improved",
    "streak": "win_streak",
    "points": "top_scorer",
    "winrate": "best_win_rate",
}


def record_finalized_tournament_history(tournament, *, include_melee_awards=False):
    """Project one genuinely finalized Tournament into permanent player records.

    Every write is protected by model-level uniqueness constraints. Repeated
    completion callbacks therefore only fill rows missing after an interrupted
    projection; existing snapshots are never rewritten from later mutable data.
    """
    if not _is_finalized_for_history(tournament):
        return {"recorded": False, "reason": "Tournament is not authoritatively final."}

    with transaction.atomic():
        from tournaments.models import Tournament

        locked_tournament = Tournament.objects.select_for_update().get(pk=tournament.pk)
        rows_created = _record_history_rows(locked_tournament)
        medals_created = _record_team_medals(locked_tournament)
        awards_created = (
            _record_melee_awards(locked_tournament)
            if include_melee_awards and locked_tournament.is_melee
            else 0
        )
    return {
        "recorded": True,
        "history_rows_created": rows_created,
        "medals_created": medals_created,
        "melee_awards_created": awards_created,
    }


def _is_finalized_for_history(tournament):
    """Apply only existing PFC terminal rules; never infer a new outcome."""
    from matches.models import Match

    matches = Match.objects.filter(tournament=tournament)
    if not matches.exists() or matches.exclude(status="completed").exists():
        return False

    if tournament.is_melee:
        # The current Mêlée engine finalizes after the configured final Stage
        # completes. This rule deliberately requires the exact configured round
        # count rather than treating a temporary no-pending-Match gap as final.
        final_stage = tournament.stages.order_by("-stage_number").first()
        if not final_stage or not final_stage.num_rounds_in_stage:
            return False
        completed_rounds = final_stage.rounds.filter(is_complete=True).count()
        return completed_rounds >= final_stage.num_rounds_in_stage

    # For standard team competition preserve the existing format-aware finality
    # predicate rather than manufacturing a separate progression rule.
    from tournaments.completion import _is_tournament_truly_finished

    return _is_tournament_truly_finished(tournament)


def _record_history_rows(tournament):
    from tournaments.models import PlayerTournamentHistory

    player_data = _completed_participation_by_player(tournament)
    created = 0
    for player_id, data in player_data.items():
        rating_change = _recorded_tournament_rating_change(data["player"], data["match_ids"])
        _entry, was_created = PlayerTournamentHistory.objects.get_or_create(
            player_id=player_id,
            tournament=tournament,
            defaults={
                "tournament_name": tournament.name,
                "tournament_date": tournament.start_date.date() if tournament.start_date else None,
                "tournament_format": _tournament_format_label(tournament),
                "represented_teams": [
                    {"id": team_id, "name": data["team_names"][team_id]}
                    for team_id in sorted(data["team_names"])
                ],
                "matches_played": len(data["match_ids"]),
                "wins": data["wins"],
                "losses": data["losses"],
                "points_scored": data["points_scored"],
                "points_against": data["points_against"],
                "rating_change": rating_change,
            },
        )
        created += int(was_created)
    return created


def _completed_participation_by_player(tournament):
    """Return actual completed-match participation, never a live Team roster."""
    from matches.models import Match, MatchPlayer
    from matches.models_participant import TeamMatchParticipant

    completed_matches = list(
        Match.objects.filter(tournament=tournament, status="completed")
        .select_related("team1", "team2", "winner", "loser")
        .order_by("id")
    )
    participants_by_match = defaultdict(list)
    for participant in (
        TeamMatchParticipant.objects.filter(
            match__in=completed_matches,
            played=True,
        )
        .select_related("player", "team")
        .order_by("match_id", "player_id")
    ):
        participants_by_match[participant.match_id].append(participant)

    snapshots_by_match = defaultdict(list)
    for snapshot in (
        MatchPlayer.objects.filter(match__in=completed_matches)
        .select_related("player", "team")
        .order_by("match_id", "player_id")
    ):
        snapshots_by_match[snapshot.match_id].append(snapshot)

    by_player = {}
    for match in completed_matches:
        # Participant rows record actual play. If a historical Match has none,
        # its activation MatchPlayer snapshots are the safe activation-onward
        # fallback. A partially populated participant side is never topped up
        # from current Team membership.
        rows = participants_by_match.get(match.id) or snapshots_by_match.get(match.id, [])
        for row in rows:
            team = row.team
            if team.id not in (match.team1_id, match.team2_id):
                continue
            data = by_player.setdefault(
                row.player_id,
                {
                    "player": row.player,
                    "match_ids": set(),
                    "team_names": {},
                    "wins": 0,
                    "losses": 0,
                    "points_scored": 0,
                    "points_against": 0,
                    "scores_available": True,
                },
            )
            if match.id in data["match_ids"]:
                continue
            data["match_ids"].add(match.id)
            data["team_names"][team.id] = team.name
            if match.winner_id == team.id:
                data["wins"] += 1
            elif match.loser_id == team.id:
                data["losses"] += 1

            if match.team1_score is None or match.team2_score is None:
                data["scores_available"] = False
            elif team.id == match.team1_id:
                data["points_scored"] += match.team1_score
                data["points_against"] += match.team2_score
            else:
                data["points_scored"] += match.team2_score
                data["points_against"] += match.team1_score

    for data in by_player.values():
        if not data.pop("scores_available"):
            data["points_scored"] = None
            data["points_against"] = None
    return by_player


def _recorded_tournament_rating_change(player, match_ids):
    """Sum only the retained rating-history entries explicitly linked to Matches."""
    try:
        history = player.profile.rating_history or []
    except Exception:
        return None
    changes = [
        Decimal(str(entry["change"]))
        for entry in history
        if entry.get("match_id") in match_ids and "change" in entry
    ]
    return sum(changes, Decimal("0")) if changes else None


def _tournament_format_label(tournament):
    return " · ".join(
        value
        for value in (tournament.get_format_display(), tournament.get_play_format_display())
        if value
    )


def _record_team_medals(tournament):
    """Persist only placements that existing PFC rules determine unambiguously."""
    if tournament.is_melee:
        # Current Mêlée has no frozen individual podium/placement record. Its
        # temporary Teams must never be converted into persistent player medals.
        return 0

    placements = _official_team_placements(tournament)
    created = 0
    for placement, team in placements:
        award_type, symbol, title = MEDAL_METADATA[placement]
        for player in _actual_tournament_players_for_team(tournament, team):
            from tournaments.models import PlayerTournamentAchievement

            _achievement, was_created = PlayerTournamentAchievement.objects.get_or_create(
                player=player,
                tournament=tournament,
                award_type=award_type,
                defaults={
                    "historical_team": team,
                    "historical_team_name": team.name,
                    "display_symbol": symbol,
                    "display_title": title,
                    "details": {"placement": placement},
                },
            )
            created += int(was_created)
    return created


def _official_team_placements(tournament):
    """Return existing-format placements or an empty result when PFC has none."""
    from matches.models import Match
    from tournaments.badges import get_tournament_final_standings

    if tournament.format in {"round_robin", "swiss", "smart_swiss"}:
        standings = get_tournament_final_standings(tournament)
        return [
            (placement, team)
            for placement, team in zip(("gold", "silver", "bronze"), standings[:3])
        ]

    if tournament.format == "knockout":
        latest_round = tournament.rounds.order_by("-number", "-id").first()
        if latest_round is None:
            return []
        finals = list(
            Match.objects.filter(
                tournament=tournament,
                round=latest_round,
                status="completed",
            ).exclude(winner__isnull=True).exclude(loser__isnull=True)
        )
        if len(finals) != 1:
            return []
        final_match = finals[0]
        # PFC does not create or store an authoritative third-place Match.
        return [("gold", final_match.winner), ("silver", final_match.loser)]

    # Multi-stage and Independent Games currently have no standalone immutable
    # placement contract. Do not convert a projection or VS points into medals.
    return []


def _actual_tournament_players_for_team(tournament, team):
    """Return a stable union of players who actually played for Team in event."""
    from matches.models import Match, MatchPlayer
    from matches.models_participant import TeamMatchParticipant

    matches = list(
        Match.objects.filter(
            tournament=tournament,
            status="completed",
        ).filter(team1=team) | Match.objects.filter(
            tournament=tournament,
            status="completed",
        ).filter(team2=team)
    )
    player_by_id = {}
    for match in matches:
        actual_rows = list(
            TeamMatchParticipant.objects.filter(match=match, team=team, played=True)
            .select_related("player")
            .order_by("player_id")
        )
        rows = actual_rows
        if not rows:
            rows = list(
                MatchPlayer.objects.filter(match=match, team=team)
                .select_related("player")
                .order_by("player_id")
            )
        for row in rows:
            player_by_id[row.player_id] = row.player
    return [player_by_id[player_id] for player_id in sorted(player_by_id)]


def _record_melee_awards(tournament):
    from tournaments.melee_leaderboard_view import calculate_melee_badges
    from tournaments.models import PlayerTournamentAchievement
    from tournaments.partnership_models import MeleePlayerStats

    stats_list = list(
        MeleePlayerStats.objects.filter(tournament=tournament).select_related("player")
    )
    badge_map = calculate_melee_badges(stats_list)
    stats_by_player_id = {stats.player_id: stats for stats in stats_list}
    created = 0
    for player_id, badges in badge_map.items():
        stats = stats_by_player_id[player_id]
        for badge in badges:
            award_type = MELEE_AWARD_TYPES[badge["type"]]
            _achievement, was_created = PlayerTournamentAchievement.objects.get_or_create(
                player_id=player_id,
                tournament=tournament,
                award_type=award_type,
                defaults={
                    "display_symbol": badge["emoji"],
                    "display_title": badge["title"],
                    "details": {
                        "matches_played": stats.matches_played,
                        "wins": stats.wins,
                        "losses": stats.losses,
                        "points_scored": stats.points_scored,
                        "points_against": stats.points_against,
                        "starting_rating": float(stats.starting_rating),
                        "current_rating": float(stats.current_rating),
                        "rating_change": float(stats.current_rating - stats.starting_rating),
                    },
                },
            )
            created += int(was_created)
    return created


def profile_history_for_player(player):
    """Fetch only permanent activation-onward history for an authorized profile."""
    from tournaments.models import PlayerTournamentAchievement, PlayerTournamentHistory

    history = list(
        PlayerTournamentHistory.objects.filter(player=player)
        .select_related("tournament")
        .order_by("-tournament_date", "-tournament_id")
    )
    awards_by_tournament_id = defaultdict(list)
    for award in (
        PlayerTournamentAchievement.objects.filter(player=player)
        .select_related("tournament", "historical_team")
        .order_by("-awarded_at", "award_type")
    ):
        awards_by_tournament_id[award.tournament_id].append(award)
    for entry in history:
        entry.achievements = awards_by_tournament_id.get(entry.tournament_id, [])
    return history


HISTORY_MATCH_PAGE_SIZE = 10


def history_detail_for_player(player, entry, *, offset=0, limit=HISTORY_MATCH_PAGE_SIZE):
    """Return one bounded page of immutable Match detail for one history entry.

    The permanent ``PlayerTournamentHistory`` row remains the summary source.
    Detail rows are read only from the same actual participation/snapshot data
    used by the history projection; the mutable current ``Player.team`` is
    intentionally never consulted.
    """
    from matches.models import Match, MatchPlayer
    from matches.models_participant import TeamMatchParticipant

    offset = max(int(offset or 0), 0)
    limit = min(max(int(limit or HISTORY_MATCH_PAGE_SIZE), 1), HISTORY_MATCH_PAGE_SIZE)

    completed_match_filters = {
        "match__tournament_id": entry.tournament_id,
        "match__status": "completed",
    }
    actual_match_ids = TeamMatchParticipant.objects.filter(
        player=player,
        played=True,
        **completed_match_filters,
    ).values("match_id")
    snapshot_match_ids = MatchPlayer.objects.filter(
        player=player,
        **completed_match_filters,
    ).exclude(match_id__in=actual_match_ids).values("match_id")

    # Fetch one extra Match only to determine whether a following page exists.
    # The initial profile never issues this query; it runs after an explicit
    # expansion and remains bounded regardless of tournament age.
    completed_matches = list(
        Match.objects.filter(
            models.Q(id__in=actual_match_ids) | models.Q(id__in=snapshot_match_ids)
        )
        .select_related("team1", "team2", "winner", "loser", "court", "round")
        .order_by("-end_time", "-id")[offset:offset + limit + 1]
    )
    has_more = len(completed_matches) > limit
    page_matches = completed_matches[:limit]
    if not page_matches:
        return [], False, None

    actual_by_match_id = {
        participant.match_id: participant
        for participant in TeamMatchParticipant.objects.filter(
            player=player,
            played=True,
            match__in=page_matches,
        ).select_related("team")
    }
    snapshot_by_match_id = {
        snapshot.match_id: snapshot
        for snapshot in MatchPlayer.objects.filter(
            player=player,
            match__in=page_matches,
        ).exclude(match_id__in=actual_by_match_id).select_related("team")
    }

    rows = []
    for match in page_matches:
        participant = actual_by_match_id.get(match.id) or snapshot_by_match_id.get(match.id)
        if participant is None or participant.team_id not in (match.team1_id, match.team2_id):
            continue

        player_team = participant.team
        opponent = match.team2 if player_team.id == match.team1_id else match.team1
        if player_team.id == match.team1_id:
            player_score, opponent_score = match.team1_score, match.team2_score
        else:
            player_score, opponent_score = match.team2_score, match.team1_score

        if match.winner_id == player_team.id:
            outcome = "win"
        elif match.loser_id == player_team.id:
            outcome = "loss"
        else:
            outcome = "draw"

        rows.append(
            {
                "match": match,
                "team": player_team,
                "opponent": opponent,
                "player_score": player_score,
                "opponent_score": opponent_score,
                "outcome": outcome,
                "role": getattr(participant, "role", None) or getattr(participant, "position", None),
            }
        )

    next_offset = offset + len(rows)
    return rows, has_more, next_offset if has_more else None
