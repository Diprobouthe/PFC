"""
friendly_games/presence_utils.py
─────────────────────────────────
Court presence registration and lifecycle management for friendly games.

Reuses the BillboardEntry / AT_COURTS mechanism already used by
matches/views.py::auto_register_players_to_billboard().

Game-generated presence entries are tagged with:
  presence_source = 'friendly_game'
  game_ref        = 'friendly:<game.id>'

This allows them to be deactivated precisely when the game ends,
without touching manual check-ins or other games' entries.

Called from:
  - start_game()        → register all players when game goes ACTIVE
  - game ends/validates → deactivate_friendly_game_presence(game)
  - game cancelled      → deactivate_friendly_game_presence(game)
  - game expires        → deactivate_friendly_game_presence(game)
"""

import logging
from django.utils import timezone
from billboard.models import BillboardEntry
from friendly_games.models import PlayerCodename
from courts.timezone_utils import get_court_local_date

logger = logging.getLogger(__name__)


# ── Registration ──────────────────────────────────────────────────────────────

def register_friendly_game_players_at_court(game):
    """
    Register all players in *game* as AT_COURTS on the Billboard.

    - Skips if game has no court_complex assigned
    - Skips players without a codename
    - Idempotent: if the player already has an active game-generated entry
      for this specific game, a duplicate is not created
    - Tags every created entry with presence_source='friendly_game' and
      game_ref='friendly:<game.id>' so it can be deactivated on game end

    Never raises — failures are logged and swallowed so the game flow
    is never interrupted.
    """
    try:
        if not game.court_complex:
            logger.info(
                f"FriendlyGame {game.id} has no court_complex — "
                "skipping Billboard presence registration"
            )
            return

        court_complex = game.court_complex
        game_ref = f"friendly:{game.id}"
        game_players = game.players.all().select_related('player')

        for game_player in game_players:
            player = game_player.player
            try:
                player_codename_obj = PlayerCodename.objects.get(player=player)
                codename = player_codename_obj.codename

                # Idempotent: skip if this game already has an active entry for this player
                already_registered = BillboardEntry.objects.filter(
                    codename=codename,
                    action_type='AT_COURTS',
                    court_complex=court_complex,
                    game_ref=game_ref,
                    is_active=True,
                ).exists()

                if not already_registered:
                    BillboardEntry.objects.create(
                        codename=codename,
                        action_type='AT_COURTS',
                        court_complex=court_complex,
                        message='Auto-registered via friendly game activation',
                        is_active=True,
                        presence_source=BillboardEntry.PRESENCE_SOURCE_FRIENDLY,
                        game_ref=game_ref,
                    )
                    logger.info(
                        f"Friendly game {game.id}: registered player "
                        f"{player.name} ({codename}) at {court_complex.name}"
                    )
                else:
                    logger.debug(
                        f"Friendly game {game.id}: player {player.name} "
                        f"already registered for this game — skipped"
                    )

            except PlayerCodename.DoesNotExist:
                logger.warning(
                    f"Friendly game {game.id}: player {player.name} (id={player.id}) "
                    "has no codename — skipping Billboard registration"
                )
                continue

    except Exception as exc:
        logger.error(
            f"Error registering friendly game {game.id} players to Billboard: {exc}"
        )


# ── Deactivation ──────────────────────────────────────────────────────────────

def deactivate_friendly_game_presence(game):
    """
    Deactivate all AT_COURTS entries that were created for *game*.

    Only touches entries tagged with game_ref='friendly:<game.id>'.
    Manual check-ins and other games' entries are never affected.
    Historical records are preserved (is_active=False, not deleted).

    Safe to call multiple times — idempotent.
    Never raises.
    """
    try:
        game_ref = f"friendly:{game.id}"
        count = BillboardEntry.objects.filter(
            action_type='AT_COURTS',
            game_ref=game_ref,
            is_active=True,
        ).update(is_active=False)

        if count:
            logger.info(
                f"Friendly game {game.id}: deactivated {count} presence "
                f"entry/entries at game end/cancel/expire"
            )
        else:
            logger.debug(
                f"Friendly game {game.id}: no active presence entries to deactivate"
            )

    except Exception as exc:
        logger.error(
            f"Error deactivating presence for friendly game {game.id}: {exc}"
        )
