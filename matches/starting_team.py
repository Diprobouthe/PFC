"""Persisted selected-side draw for tournament Match starts.

The draw is deliberately isolated from Match scoring, validation, progression,
and LiveScoreboard data.  It records one of the Match's existing historical
Team sides only after the Match enters ``active``.
"""

from secrets import choice

from django.db import transaction
from django.db.models import Q


def ensure_match_starting_team(match):
    """Return ``(team, newly_selected)`` for an active tournament Match.

    The Match row is locked so duplicate activation/promotion callbacks retain
    the first persisted draw rather than selecting a second side.  The supplied
    in-memory Match object is updated with the stored ID for callers that need
    to render or notify immediately after the transition.
    """
    if not match or not match.pk:
        return None, False

    with transaction.atomic():
        locked_match = (
            # ``starting_team`` is nullable until this first draw.  Lock only
            # the Match row so PostgreSQL does not attempt FOR UPDATE on the
            # nullable OUTER JOIN created by ``select_related`` below.
            type(match).objects.select_for_update(of=("self",))
            .select_related("team1", "team2", "starting_team")
            .get(pk=match.pk)
        )
        if locked_match.starting_team_id:
            match.starting_team_id = locked_match.starting_team_id
            return locked_match.starting_team, False

        if not locked_match.team1_id or not locked_match.team2_id:
            return None, False

        selected_team_id = choice((locked_match.team1_id, locked_match.team2_id))
        locked_match.starting_team_id = selected_team_id
        locked_match.save(update_fields=["starting_team", "updated_at"])
        match.starting_team_id = selected_team_id
        return (
            locked_match.team1
            if selected_team_id == locked_match.team1_id
            else locked_match.team2
        ), True


def announce_match_starting_team(match):
    """Persist the draw and retain existing selected-side-only push semantics."""
    selected_team, newly_selected = ensure_match_starting_team(match)
    if not selected_team or not newly_selected:
        return selected_team

    # The selected Match side is resolved from its historical Match roster.
    # Notification delivery remains best-effort and never changes activation.
    try:
        from matches.melee_roster_resolution import players_for_match_team
        from pfc_events.push_notifications import notify_match_action_required

        notify_match_action_required(
            list(players_for_match_team(match, selected_team)),
            "match_starts",
            "match",
            match.id,
        )
    except Exception:
        # The draw is already durable. A Push delivery failure must not alter an
        # activated Match or cause a replacement draw on a retry.
        pass
    return selected_team


def match_has_first_real_score(match):
    """Whether an official LiveScoreboard update has recorded a non-zero score."""
    if not match or not match.pk:
        return False
    try:
        scoreboard = match.live_scoreboard
    except Exception:
        return False
    return scoreboard.score_updates.filter(
        Q(team1_score__gt=0) | Q(team2_score__gt=0)
    ).exists()
