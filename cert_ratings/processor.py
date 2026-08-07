"""
cert_ratings.processor
======================
Processes Certifying Entity Elo ratings after a tournament match completes.

Design principles:
  - Completely isolated from the existing PFC Rating system.
  - A failure here must never affect match completion or existing ratings.
  - Idempotent: the same match can be passed multiple times safely.
  - Uses database transactions for atomicity.
  - Friendly games are never processed here.
"""

import logging
from django.db import transaction

from .models import CertifyingEntity, PlayerCertRating, CertRatingHistory
from .elo import calculate_team_elo_change

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def process_match_cert_ratings(match):
    """
    Update Certifying Entity Elo ratings after a tournament match completes.

    Called from matches/views.py immediately after update_tournament_match_ratings.
    Wrapped in a try/except by the caller so any exception here is logged but
    never propagates to the match completion flow.

    Args:
        match: A completed matches.Match instance.

    Returns:
        dict with keys: success (bool), reason (str), updates (list).
    """
    # ── Pre-flight checks ────────────────────────────────────────────────────
    if not match or match.status != "completed":
        return {"success": False, "reason": "Match not completed"}

    if not match.winner or not match.loser:
        return {"success": True, "reason": "Draw — no Elo change"}

    tournament = getattr(match, "tournament", None)
    if not tournament:
        return {"success": True, "reason": "No tournament on match"}

    # Certifying Entity is stored on the Tournament (added in Phase 3)
    entity = getattr(tournament, "certifying_entity", None)
    if not entity:
        return {"success": True, "reason": "Tournament is not certified"}

    if not entity.is_active:
        return {"success": True, "reason": f"Certifying entity '{entity.name}' is inactive"}

    if entity.rating_system != "classic_elo":
        return {
            "success": False,
            "reason": f"Unknown rating system '{entity.rating_system}' for entity '{entity.name}'",
        }

    # ── Idempotency check ────────────────────────────────────────────────────
    # If any history row already exists for this match + entity, skip entirely.
    already_processed = CertRatingHistory.objects.filter(
        entity=entity,
        match=match,
    ).exists()
    if already_processed:
        logger.info(
            f"Match {match.id}: cert ratings for '{entity.name}' already processed — skipping"
        )
        return {"success": True, "reason": "Already processed (idempotent skip)"}

    # ── Gather participants ──────────────────────────────────────────────────
    from matches.rating_integration import get_match_participants

    winner_players = get_match_participants(match, match.winner)
    loser_players = get_match_participants(match, match.loser)

    if not winner_players and not loser_players:
        return {"success": True, "reason": "No participants found"}

    # ── Retrieve / initialise ratings ────────────────────────────────────────
    def _get_or_create_rating(player):
        obj, _ = PlayerCertRating.objects.get_or_create(
            player=player,
            entity=entity,
            defaults={"current_rating": float(entity.elo_starting_rating)},
        )
        return obj

    winner_rating_objs = [_get_or_create_rating(p) for p in winner_players]
    loser_rating_objs  = [_get_or_create_rating(p) for p in loser_players]

    winner_ratings = [r.current_rating for r in winner_rating_objs]
    loser_ratings  = [r.current_rating for r in loser_rating_objs]

    # ── Calculate Elo changes ────────────────────────────────────────────────
    winner_change = calculate_team_elo_change(
        team_ratings=winner_ratings,
        opponent_team_ratings=loser_ratings,
        team_won=True,
        k_factor=entity.elo_k_factor,
        scale=entity.elo_scale,
    )
    loser_change = calculate_team_elo_change(
        team_ratings=loser_ratings,
        opponent_team_ratings=winner_ratings,
        team_won=False,
        k_factor=entity.elo_k_factor,
        scale=entity.elo_scale,
    )

    # ── Persist atomically ───────────────────────────────────────────────────
    updates = []
    try:
        with transaction.atomic():
            for rating_obj in winner_rating_objs:
                old = rating_obj.current_rating
                new = old + winner_change
                CertRatingHistory.objects.create(
                    player=rating_obj.player,
                    entity=entity,
                    match=match,
                    rating_before=old,
                    rating_after=new,
                    rating_change=winner_change,
                )
                rating_obj.current_rating = new
                rating_obj.matches_played += 1
                rating_obj.save(update_fields=["current_rating", "matches_played", "updated_at"])
                updates.append({
                    "player": rating_obj.player.name,
                    "entity": entity.name,
                    "old": old,
                    "new": new,
                    "change": winner_change,
                    "result": "win",
                })
                logger.info(
                    f"[{entity.name}] {rating_obj.player.name}: "
                    f"{old:.1f} → {new:.1f} (+{winner_change:.1f}) WIN"
                )

            for rating_obj in loser_rating_objs:
                old = rating_obj.current_rating
                new = old + loser_change
                CertRatingHistory.objects.create(
                    player=rating_obj.player,
                    entity=entity,
                    match=match,
                    rating_before=old,
                    rating_after=new,
                    rating_change=loser_change,
                )
                rating_obj.current_rating = new
                rating_obj.matches_played += 1
                rating_obj.save(update_fields=["current_rating", "matches_played", "updated_at"])
                updates.append({
                    "player": rating_obj.player.name,
                    "entity": entity.name,
                    "old": old,
                    "new": new,
                    "change": loser_change,
                    "result": "loss",
                })
                logger.info(
                    f"[{entity.name}] {rating_obj.player.name}: "
                    f"{old:.1f} → {new:.1f} ({loser_change:.1f}) LOSS"
                )

    except Exception as e:
        logger.error(
            f"Match {match.id}: cert rating transaction failed for '{entity.name}': {e}"
        )
        return {"success": False, "reason": str(e)}

    logger.info(
        f"Match {match.id}: cert ratings for '{entity.name}' updated "
        f"({len(updates)} players)"
    )
    return {"success": True, "reason": "OK", "updates": updates}
