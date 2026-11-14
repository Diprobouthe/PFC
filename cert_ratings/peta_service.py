"""PETA Certified Entity storage adapter.

Only the certified rating rows change; the global PFC PlayerProfile rating is
updated by the existing PFC lifecycle exactly once. No live-page queries.
"""
import json
import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import CertRatingHistory, PlayerCertRating
from .peta_models import PetaCompetitor, PetaEvent, PetaEventEntry
from .peta_core import pfc_match_delta, protected_entry_rating
from .peta_policy import (
    MULTIPLIERS, TOP_FRACTION, BASE_FRACTION, MIDDLE_SHARE,
    MIN_WIN_RATE_MATCHES, MIN_WIN_RATE, awards_for_player,
)
from .peta_series import EventPlayer, settle_event

logger = logging.getLogger(__name__)


def peta_event_for_tournament(tournament):
    entity = getattr(tournament, "certifying_entity", None)
    if not entity or entity.rating_system != "peta_algorithm":
        return None
    event = PetaEvent.objects.select_related("series", "series__entity").filter(
        tournament_id=tournament.pk, series__entity=entity,
    ).first()
    if event is None:
        raise ValueError(
            f"PETA event mapping missing for tournament #{tournament.pk}. "
            "Configure its PETA Series and Event (ordinal 1-8) in Django admin "
            "before generating teams."
        )
    return event


def freeze_peta_entries(tournament, melee_players):
    """Freeze a whole roster before the FIRST Snake Draft or match.

    Subsequent calls are no-ops for existing entries. Entry snapshots use the
    GLOBAL PFC value only once, never after match rating projection has begun.
    """
    event = peta_event_for_tournament(tournament)
    if event is None:
        return {}
    player_ids = sorted({row.player_id for row in melee_players})
    if not player_ids:
        return {}
    from teams.models import PlayerProfile
    with transaction.atomic():
        locked = PetaEvent.objects.select_for_update().get(pk=event.pk)
        if locked.settled_at:
            raise ValueError("Cannot freeze entries of a settled PETA event")
        if PetaEvent.objects.filter(
            series=event.series, ordinal__lt=event.ordinal,
            settled_at__isnull=True,
        ).exists():
            raise ValueError("Previous PETA event must settle before the next begins")
        profile_values = dict(PlayerProfile.objects.filter(
            player_id__in=player_ids).values_list("player_id", "value"))
        existing = dict(PetaEventEntry.objects.filter(
            event=event).values_list("player_id", "entry_rating"))
        # Never silently replace a frozen roster with a different roster.
        if set(existing) - set(player_ids):
            raise ValueError("PETA roster changed after entry freeze")
        for player_id in player_ids:
            if player_id in existing:
                continue
            competitor, _ = PetaCompetitor.objects.get_or_create(
                series=event.series, player_id=player_id)
            rating = protected_entry_rating(
                profile_values.get(player_id, 100.0), competitor.last_end_rating)
            PetaEventEntry.objects.create(
                event=event, player_id=player_id, entry_rating=rating)
            PlayerCertRating.objects.update_or_create(
                entity=event.series.entity, player_id=player_id,
                defaults={"current_rating": rating})
            existing[player_id] = rating
    return existing


def peta_entry_ratings(tournament):
    event = peta_event_for_tournament(tournament)
    return {} if event is None else dict(
        PetaEventEntry.objects.filter(event=event)
        .values_list("player_id", "entry_rating")
    )


def process_peta_match(match, entity):
    """Persist one certified-rating projection per completed Match.

    Each participant receives an individual delta against the PRE-match opposing team average.
    A retry cannot update a player twice because immutable history is unique.
    """
    if match.status != "completed" or not match.winner_id or not match.loser_id:
        return {"success": False, "reason": "Completed match and winner required"}
    try:
        event = PetaEvent.objects.get(
            tournament_id=match.tournament_id, series__entity=entity)
    except PetaEvent.DoesNotExist:
        return {"success": False, "reason": "No PETA Series event mapping"}

    from matches.rating_integration import get_match_participants
    winners = list(get_match_participants(match, match.winner))
    losers = list(get_match_participants(match, match.loser))
    winner_ids = [p.pk for p in winners]
    loser_ids = [p.pk for p in losers]
    ids = winner_ids + loser_ids
    if not winner_ids or not loser_ids or len(ids) != len(set(ids)):
        return {"success": False, "reason": "Incomplete or duplicated match roster"}
    try:
        with transaction.atomic():
            if PetaEventEntry.objects.filter(event=event, player_id__in=ids).count() != len(ids):
                raise ValueError("Missing pre-match frozen PETA entries")
            rating_rows = list(PlayerCertRating.objects.select_for_update().filter(
                entity=entity, player_id__in=ids).order_by("pk"))
            ratings = {row.player_id: row for row in rating_rows}
            if set(ratings) != set(ids):
                raise ValueError("Missing PETA certified rating rows")
            prior_ids = set(CertRatingHistory.objects.filter(
                entity=entity, match=match).values_list("player_id", flat=True))
            if prior_ids:
                if prior_ids != set(ids):
                    raise ValueError("Partial PETA match history; retry requires repair")
                return {"success": True, "reason": "Already processed", "updates": []}
            winners_score = match.team1_score if match.winner_id == match.team1_id else match.team2_score
            losers_score = match.team2_score if match.winner_id == match.team1_id else match.team1_score
            winner_ratings = [ratings[i].current_rating for i in winner_ids]
            loser_ratings = [ratings[i].current_rating for i in loser_ids]
            winner_opponent_average = sum(loser_ratings) / len(loser_ratings)
            loser_opponent_average = sum(winner_ratings) / len(winner_ratings)
            updates = []
            for side, opponent_average, own_score, opponent_score in (
                (winner_ids, winner_opponent_average, winners_score, losers_score),
                (loser_ids, loser_opponent_average, losers_score, winners_score),
            ):
                for player_id in side:
                    cert = ratings[player_id]
                    old = cert.current_rating
                    delta = pfc_match_delta(
                        own_rating=old, opponent_average_rating=opponent_average,
                        own_score=own_score, opponent_score=opponent_score)
                    new = max(0.0, old + delta)
                    CertRatingHistory.objects.create(
                        entity=entity, match=match, player_id=player_id,
                        rating_before=old, rating_after=new, rating_change=new-old)
                    cert.current_rating = new
                    cert.matches_played += 1
                    cert.save(update_fields=["current_rating", "matches_played", "updated_at"])
                    updates.append({"player_id": player_id, "change": round(new - old, 2)})
            return {"success": True, "reason": "OK", "updates": updates}
    except Exception:
        logger.exception("PETA certified match processing failed for %s", match.pk)
        return {"success": False, "reason": "Retryable PETA projection failure"}


def _contributing_player_ids(tournament, player_ids):
    """Require an actual score update or tracked shot in EVERY played match.

    Match tracking credits the tracked participant, not the browser operator.
    An empty authorization, a shot in another match, or an earlier event
    never qualifies a player for this event's dividend.
    """
    from friendly_games.models import PlayerCodename
    from matches.models import MatchPlayer, ScoreUpdate
    from match_tracking.models import TrackingPracticeSession

    match_players = list(MatchPlayer.objects.filter(
        match__tournament=tournament, match__status="completed",
        player_id__in=player_ids,
    ).values_list("match_id", "player_id"))
    required = {}
    for match_id, player_id in match_players:
        required.setdefault(player_id, set()).add(match_id)

    codes = dict(PlayerCodename.objects.filter(
        player_id__in=player_ids).values_list("codename", "player_id"))
    scored = set()
    for match_id, code in ScoreUpdate.objects.filter(
        scoreboard__tournament_match__tournament=tournament,
        scoreboard__tournament_match__status="completed",
        scorekeeper_codename__in=list(codes),
        update_type__in=("increment", "correction"),
    ).exclude(team1_score=0, team2_score=0).values_list(
        "scoreboard__tournament_match_id", "scorekeeper_codename"
    ).distinct():
        player_id = codes.get(code)
        if match_id in required.get(player_id, set()):
            scored.add((match_id, player_id))

    tracked = set(TrackingPracticeSession.objects.filter(
        tracking_session__match_type="match",
        tracking_session__match_pk__in=[match_id for match_id, _ in match_players],
        player_id__in=player_ids,
        practice_session__total_shots__gt=0,
    ).values_list("tracking_session__match_pk", "player_id").distinct())
    contributed = scored | tracked
    return {
        player_id for player_id, match_ids in required.items()
        if match_ids and all((match_id, player_id) in contributed for match_id in match_ids)
    }


def settle_peta_tournament(tournament):
    """Settle exactly once at AUTHORITATIVE event completion.

    The caller owns the existing Round lifecycle transaction. Settlement writes
    PETA series balances and freezes a full audit snapshot; no PFC global write.
    """
    event = peta_event_for_tournament(tournament)
    if event is None:
        return {"settled": False, "reason": "Not PETA"}
    if not tournament.is_melee:
        raise ValueError("PETA currently requires a Mêlée tournament")
    from matches.models import Match, MatchPlayer
    from tournaments.partnership_models import MeleePlayerStats
    with transaction.atomic():
        locked = PetaEvent.objects.select_for_update().get(pk=event.pk)
        if locked.settled_at:
            return {"settled": True, "reason": "Already settled"}
        if locked.require_task:
            raise ValueError("Task settlement is not implemented; do not silently ignore tasks")
        if tournament.automation_status != "completed":
            raise ValueError("Cannot settle before tournament is finished")
        if Match.objects.filter(tournament=tournament).exclude(status="completed").exists():
            raise ValueError("Incomplete matches prevent final settlement")
        entries = list(PetaEventEntry.objects.select_for_update().filter(
            event=locked).order_by("player_id"))
        player_ids = [e.player_id for e in entries]
        roster = set(tournament.melee_players.values_list("player_id", flat=True))
        if not player_ids or set(player_ids) != roster:
            raise ValueError("PETA event entrants do not match frozen roster")
        stats = {s.player_id: s for s in MeleePlayerStats.objects.filter(
            tournament=tournament, player_id__in=player_ids)}
        certs = {c.player_id: c for c in PlayerCertRating.objects.filter(
            entity=locked.series.entity, player_id__in=player_ids)}
        competitors = {c.player_id: c for c in PetaCompetitor.objects.select_for_update().filter(
            series=locked.series, player_id__in=player_ids).order_by("player_id")}
        if set(stats) != roster or set(certs) != roster or set(competitors) != roster:
            raise ValueError("Missing player stats, certified ratings or series balances")
        # Verify that EVERY completed-match player has a matching PETA rating
        # history row: partial asynchronous processing must never get a dividend.
        from collections import Counter
        expected = Counter(MatchPlayer.objects.filter(
            match__tournament=tournament, match__status="completed")
            .values_list("player_id", flat=True))
        actual = Counter(CertRatingHistory.objects.filter(
            entity=locked.series.entity, match__tournament=tournament)
            .values_list("player_id", flat=True))
        if expected != actual:
            raise ValueError("Incomplete PETA certified match projection")
        top_score = max(stats[i].points_scored for i in player_ids)
        qualified = [stats[i] for i in player_ids if stats[i].matches_played >= MIN_WIN_RATE_MATCHES]
        max_winrate = max(
            (Decimal(s.wins) / Decimal(s.matches_played) for s in qualified),
            default=Decimal(0))
        contributors = _contributing_player_ids(tournament, player_ids)
        entry_by_id = {entry.player_id: entry for entry in entries}
        ranks = sorted(player_ids, key=lambda i: (
            -(certs[i].current_rating - entry_by_id[i].entry_rating), -stats[i].wins, i))
        podium = {player_id: rank for rank, player_id in enumerate(ranks, 1)}
        inputs = []
        awards_by_id = {}
        for entry in entries:
            player_id = entry.player_id
            s = stats[player_id]
            ratio = (Decimal(s.wins) / Decimal(s.matches_played)
                     if s.matches_played else Decimal(0))
            awards = awards_for_player(
                best_streak=s.best_performance,
                top_points=s.points_scored > 0 and s.points_scored == top_score,
                best_win_rate=(
                    s.matches_played >= MIN_WIN_RATE_MATCHES
                    and ratio >= MIN_WIN_RATE and ratio == max_winrate),
                podium_rank=podium[player_id],
                include_podium=True,  # PETA series always awards podium 3/2/1.
            )
            awards_by_id[player_id] = awards
            inputs.append(EventPlayer(
                player_id=player_id,
                prior_travel_points=competitors[player_id].travel_points,
                rating_delta=round(certs[player_id].current_rating - entry.entry_rating, 2),
                awards=awards,
                dividend_eligible=(
                    player_id in contributors and not competitors[player_id].dividend_suspended),
                keep_all_now=entry.use_exception,
                exception_used_before=competitors[player_id].exception_used,
            ))
        result = settle_event(
            inputs, multiplier=MULTIPLIERS[locked.ordinal - 1],
            middle_fraction=MIDDLE_SHARE,
            top_fraction=TOP_FRACTION, base_fraction=BASE_FRACTION)
        for entry in entries:
            player_id = entry.player_id
            comp = competitors[player_id]
            own_before = Decimal(comp.travel_points)
            final = result["travel_points_after"][player_id]
            entry.end_rating = certs[player_id].current_rating
            entry.eligible_for_dividend = bool(
                player_id in contributors and not comp.dividend_suspended)
            entry.personal_earnings = result["personal_points"][player_id] - own_before
            entry.dividend = result["dividends"][player_id]
            entry.save(update_fields=[
                "end_rating", "eligible_for_dividend", "personal_earnings", "dividend"])
            comp.travel_points = final
            comp.last_end_rating = certs[player_id].current_rating
            comp.exception_used = comp.exception_used or entry.use_exception
            comp.save(update_fields=["travel_points", "last_end_rating", "exception_used"])
        locked.settlement_audit = json.loads(json.dumps({
            "event": locked.ordinal,
            "pool": result["pool"],
            "distributed": result["distributed"],
            "undistributed": result["undistributed"],
            "classes": result["classes"],
            "dividends": result["dividends"],
            "awards": {pid: {k: str(v) for k, v in awards.items()} for pid, awards in awards_by_id.items()},
            "ranks_pre_dividend": result["rank_pre_dividend"],
            "travel_points_after": result["travel_points_after"],
        }, default=str))
        locked.settled_at = timezone.now()
        locked.save(update_fields=["settlement_audit", "settled_at"])
        return {"settled": True, "pool": str(result["pool"]), "players": len(player_ids)}
