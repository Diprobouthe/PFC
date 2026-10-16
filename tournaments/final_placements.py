"""Authoritative Final Four podium, derived only from official Match winners.

Shared bronze requires two completed semifinals and one completed championship
final. An optional third-place Match ranks those two semifinal losers 3/4.
No provisional result, Swiss tie-breaker, or active roster can override a final.
Read-only. Historic single-final Match records without placement_role are
supported when their semifinal/final Round structure is unambiguous.
"""

from matches.models import Match


def final_four_podium(tournament):
    """Return {Team ID: {'rank': int, 'status': str}} or None if not final."""
    if tournament.format != "multi_stage" or tournament.is_melee:
        return None

    final_stage = tournament.stages.order_by("-stage_number").first()
    if not final_stage or final_stage.format != "knockout":
        return None
    rounds = list(final_stage.rounds.order_by("number_in_stage", "id"))
    if len(rounds) < 2:
        return None

    semifinal_round, championship_round = rounds[-2:]
    semis = list(
        Match.objects.filter(
            tournament=tournament, round=semifinal_round,
            status="completed",
        ).order_by("id")
    )
    if len(semis) != 2 or any(not m.winner_id or not m.loser_id for m in semis):
        return None
    semi_winners = {m.winner_id for m in semis}
    semi_losers = {m.loser_id for m in semis}
    if (len(semi_winners) != 2 or len(semi_losers) != 2
            or semi_winners & semi_losers):
        return None

    final_matches = list(
        Match.objects.filter(tournament=tournament, round=championship_round)
        .order_by("id")
    )
    championship = [m for m in final_matches if m.placement_role == "championship_final"]
    bronze = [m for m in final_matches if m.placement_role == "third_place_playoff"]
    if not championship and len(final_matches) == 1:
        # Support existing 15-match historical events.
        championship = final_matches
    if len(championship) != 1 or len(final_matches) != 1 + int(final_stage.third_place_playoff):
        return None
    gold_match = championship[0]
    if (gold_match.status != "completed"
            or not gold_match.winner_id or not gold_match.loser_id
            or {gold_match.team1_id, gold_match.team2_id} != semi_winners):
        return None

    podium = {
        gold_match.winner_id: {"rank": 1, "status": "champion"},
        gold_match.loser_id: {"rank": 2, "status": "finalist"},
    }
    if final_stage.third_place_playoff:
        if len(bronze) != 1:
            return None
        match = bronze[0]
        if (match.status != "completed" or not match.winner_id or not match.loser_id
                or {match.team1_id, match.team2_id} != semi_losers):
            return None
        podium[match.winner_id] = {"rank": 3, "status": "third_place"}
        podium[match.loser_id] = {"rank": 4, "status": "fourth_place"}
    else:
        for team_id in semi_losers:
            podium[team_id] = {"rank": 3, "status": "shared_third"}
    return podium
