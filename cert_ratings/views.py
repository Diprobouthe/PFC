"""
cert_ratings.views
==================
Player-facing Certifying Entity ratings page.
"""

import json
from django.shortcuts import render, get_object_or_404
from django.utils import timezone

from teams.models import Player
from .models import PlayerCertRating, CertRatingHistory, CertifyingEntity


def player_cert_ratings(request, player_id):
    """
    Show a player's Certifying Entity ratings.

    Displays one card per entity in which the player has rating data,
    with current rating, matches played, and a rating progression chart
    reusing the same data format as the existing PFC Rating chart.
    """
    player = get_object_or_404(Player, id=player_id)

    # All cert ratings for this player, ordered by entity name
    cert_ratings = (
        PlayerCertRating.objects
        .filter(player=player)
        .select_related("entity")
        .order_by("entity__name")
    )

    # Build chart data for each entity (same structure as existing PFC rating chart)
    entity_data = []
    for cr in cert_ratings:
        history_qs = (
            CertRatingHistory.objects
            .filter(player=player, entity=cr.entity)
            .order_by("timestamp")
            .values("rating_before", "rating_after", "rating_change", "timestamp", "match_id")
        )
        history = list(history_qs)

        # Build chart points: starting point + one point per match
        chart_points = []
        if history:
            # First point: rating before the first match
            chart_points.append({
                "x": history[0]["timestamp"].strftime("%Y-%m-%d"),
                "y": round(history[0]["rating_before"], 1),
                "label": "Start",
            })
            for h in history:
                sign = "+" if h["rating_change"] >= 0 else ""
                chart_points.append({
                    "x": h["timestamp"].strftime("%Y-%m-%d"),
                    "y": round(h["rating_after"], 1),
                    "label": f"Match {h['match_id']} ({sign}{h['rating_change']:.1f})",
                })

        starting_rating = history[0]["rating_before"] if history else cr.current_rating
        total_change = cr.current_rating - starting_rating

        entity_data.append({
            "entity": cr.entity,
            "current_rating": cr.current_rating,
            "matches_played": cr.matches_played,
            "starting_rating": starting_rating,
            "total_change": total_change,
            "has_data": len(chart_points) > 1,
            "chart_points_json": json.dumps(chart_points),
            "history": history,
        })

    # Determine if this is the player's own profile (same session codename)
    is_own_profile = False
    codename = request.session.get("player_codename")
    if codename:
        try:
            from friendly_games.models import PlayerCodename
            pc = PlayerCodename.objects.get(codename=codename.upper())
            is_own_profile = (pc.player_id == player_id)
        except Exception:
            pass

    context = {
        "player": player,
        "entity_data": entity_data,
        "is_own_profile": is_own_profile,
        "all_entities": CertifyingEntity.objects.filter(is_active=True).order_by("name"),
    }
    return render(request, "cert_ratings/player_cert_ratings.html", context)
