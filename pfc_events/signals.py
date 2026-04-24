"""
pfc_events/signals.py
=====================
Server-authoritative broadcast helpers.

Architecture contract (single-source-of-truth):
  - State changes happen ONLY in Django HTTP views.
  - After saving, views call notify_match_state_changed() or notify_game_state_changed().
  - These helpers compute the next destination URL for EVERY player involved
    in the match RIGHT NOW, then push a fat payload over WebSocket.
  - Clients receive {next_url, new_status} and navigate directly.
  - Clients NEVER poll /my-matches/next-url/ or call location.reload().

Two channel groups are used per match:
  1. "match_{id}" / "game_{id}"  — shared group (spectators, scoreboard_embed)
  2. "player_{codename}"         — personal group (each participant)

The personal group carries a personalised next_url so the client navigates
without any follow-up HTTP request.

Payload shape:
    {
        "type":       "match.state_changed",
        "match_type": "tournament" | "friendly",
        "match_id":   <int>,
        "new_status": "<status string>",
        "next_url":   "/matches/detail/3/" | null
    }
"""

import logging
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

logger = logging.getLogger('pfc_events')


# ---------------------------------------------------------------------------
# Internal: compute next_url for a single player
# ---------------------------------------------------------------------------

def _next_url_for_player(player, player_team, match_type):
    """
    Delegate to smart_router helpers to compute the single best next_url
    for this player right now.  Returns a URL string or None.
    """
    try:
        from pfc_core.smart_router import (
            _resolve_tournament_matches,
            _resolve_friendly_games,
        )
        candidates = []
        if match_type == 'match':
            candidates.extend(_resolve_tournament_matches(player_team))
        else:
            candidates.extend(_resolve_friendly_games(player, player_team))

        if not candidates:
            return None
        candidates.sort(key=lambda c: c['priority'])
        return candidates[0]['url']
    except Exception as exc:
        logger.warning("_next_url_for_player failed for player %s: %s", getattr(player, 'id', '?'), exc)
        return None


# ---------------------------------------------------------------------------
# Internal: low-level group_send wrapper
# ---------------------------------------------------------------------------

def _group_send(channel_layer, group_name: str, payload: dict):
    """Fire-and-forget group_send. Logs but never raises."""
    try:
        async_to_sync(channel_layer.group_send)(group_name, payload)
    except Exception as exc:
        logger.warning("group_send to %s failed: %s", group_name, exc)


# ---------------------------------------------------------------------------
# Internal: broadcast fat payloads to shared + personal groups
# ---------------------------------------------------------------------------

def _broadcast_to_all(match_type: str, object_id: int, new_status: str,
                      team1=None, team2=None, player_list=None):
    """
    1. Push a shared payload to the match/game group (spectators).
    2. For each player, compute their next_url and push to "player_{codename}".

    player_list: [(player, player_team), ...] — used for friendly games.
    team1/team2: Team model instances — used for tournament matches.
    """
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return  # Channels not configured (unit tests)

    # 1. Shared broadcast (spectators / scoreboard_embed)
    shared_group = f"{match_type}_{object_id}"
    shared_payload = {
        "type":       "match.state_changed",
        "match_type": match_type,
        "match_id":   object_id,
        "new_status": new_status,
        "next_url":   None,
    }
    _group_send(channel_layer, shared_group, shared_payload)

    # 2. Build player list from team rosters if not supplied directly
    if player_list is None:
        player_list = []
        for team in [team1, team2]:
            if team is None:
                continue
            try:
                for p in team.players.select_related('team').all():
                    player_list.append((p, team))
            except Exception as exc:
                logger.warning("Could not iterate team %s players: %s", getattr(team, 'id', '?'), exc)

    # 3. Personal broadcast per player
    for player, player_team in player_list:
        try:
            codenames = list(player.codenames.values_list('codename', flat=True))
        except Exception:
            continue
        if not codenames:
            continue

        next_url = _next_url_for_player(player, player_team, match_type)
        personal_payload = {
            "type":       "match.state_changed",
            "match_type": match_type,
            "match_id":   object_id,
            "new_status": new_status,
            "next_url":   next_url,
        }
        for codename in codenames:
            _group_send(channel_layer, f"player_{codename}", personal_payload)


# ---------------------------------------------------------------------------
# Public API — called from views after state changes
# ---------------------------------------------------------------------------

def notify_match_state_changed(match_id: int, new_status: str, match=None):
    """
    Broadcast a state-change event for tournament match <match_id>.

    Pass the already-loaded match object to avoid an extra DB query.
    If match is None, it is fetched here.
    """
    if match is None:
        try:
            from matches.models import Match
            match = Match.objects.select_related('team1', 'team2').get(pk=match_id)
        except Exception as exc:
            logger.warning("notify_match_state_changed: cannot load match %s: %s", match_id, exc)
            # Degrade gracefully — shared group only, no personal routing
            channel_layer = get_channel_layer()
            if channel_layer:
                _group_send(channel_layer, f"match_{match_id}", {
                    "type": "match.state_changed",
                    "match_type": "match",
                    "match_id": match_id,
                    "new_status": new_status,
                    "next_url": None,
                })
            return

    _broadcast_to_all(
        match_type='match',
        object_id=match_id,
        new_status=new_status,
        team1=getattr(match, 'team1', None),
        team2=getattr(match, 'team2', None),
    )


def notify_game_state_changed(game_id: int, new_status: str, game=None):
    """
    Broadcast a state-change event for friendly game <game_id>.

    Pass the already-loaded game object to avoid an extra DB query.
    If game is None, it is fetched here.
    """
    player_list = []

    if game is None:
        try:
            from friendly_games.models import FriendlyGame
            game = FriendlyGame.objects.prefetch_related(
                'players__player__team', 'players__player__codenames'
            ).get(pk=game_id)
        except Exception as exc:
            logger.warning("notify_game_state_changed: cannot load game %s: %s", game_id, exc)
            channel_layer = get_channel_layer()
            if channel_layer:
                _group_send(channel_layer, f"game_{game_id}", {
                    "type": "match.state_changed",
                    "match_type": "game",
                    "match_id": game_id,
                    "new_status": new_status,
                    "next_url": None,
                })
            return

    try:
        for gp in game.players.select_related('player', 'player__team').all():
            if gp.player and gp.player.team:
                player_list.append((gp.player, gp.player.team))
    except Exception as exc:
        logger.warning("notify_game_state_changed: player list error: %s", exc)

    _broadcast_to_all(
        match_type='game',
        object_id=game_id,
        new_status=new_status,
        player_list=player_list,
    )
