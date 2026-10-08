"""Bulk statistics for the public Tournament Players leaderboard.

This module deliberately computes leaderboard projections in one aggregate query.
It does not change PlayerProfile's canonical/statistical methods, which remain
available for individual profile pages and other callers.
"""
from __future__ import annotations

from django.db.models import Count, F, Q

from matches.models_participant import TeamMatchParticipant


def bulk_player_leaderboard_stats(player_ids):
    """Return participation-derived overall + position stats keyed by Player id.

    Semantics match PlayerProfile.get_accurate_statistics()/get_position_stats():
    only played participations in completed Matches count; a win is attributed
    when Match.winner is the participant's recorded Team.
    """
    player_ids = list(player_ids)
    stats = {
        player_id: {
            "matches_played": 0,
            "matches_won": 0,
            "win_rate": 0.0,
            "position_stats": {},
        }
        for player_id in player_ids
    }
    if not player_ids:
        return stats

    rows = (
        TeamMatchParticipant.objects.filter(
            player_id__in=player_ids,
            played=True,
            match__status="completed",
        )
        .values("player_id", "position")
        .annotate(
            matches_played=Count("id"),
            matches_won=Count(
                "id",
                filter=Q(match__winner_id=F("team_id")),
            ),
        )
        .order_by()
    )

    for row in rows:
        player_stats = stats[row["player_id"]]
        played = row["matches_played"]
        won = row["matches_won"]
        position = row["position"]

        position_stats = {
            "matches_played": played,
            "matches_won": won,
            "win_rate": round((won / played) * 100, 1) if played else 0.0,
        }
        player_stats["position_stats"][position] = position_stats
        player_stats["matches_played"] += played
        player_stats["matches_won"] += won

    for player_stats in stats.values():
        played = player_stats["matches_played"]
        won = player_stats["matches_won"]
        player_stats["win_rate"] = (
            round((won / played) * 100, 1) if played else 0.0
        )

    return stats
