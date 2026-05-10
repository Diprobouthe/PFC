"""
friendly_games/presence_utils.py
─────────────────────────────────
Court presence registration for friendly games.

Reuses the exact same BillboardEntry / AT_COURTS mechanism already used by
matches/views.py::auto_register_players_to_billboard().

Called from:
  - activate_game()  → register all players when the game goes ACTIVE
  - (future) game completion / cancellation if needed

No new tracking system is created.  All presence data flows through the
existing Billboard AT_COURTS entries, so the billboard "Currently at Courts"
count and analytics automatically include friendly game players.
"""

import logging
from django.utils import timezone
from billboard.models import BillboardEntry
from friendly_games.models import PlayerCodename
from courts.timezone_utils import get_court_local_date

logger = logging.getLogger(__name__)


def register_friendly_game_players_at_court(game):
    """
    Register all players in *game* as AT_COURTS on the Billboard.

    Mirrors matches/views.py::auto_register_players_to_billboard() exactly:
      - Skips if game has no court_complex assigned
      - Skips players without a codename
      - Skips players already registered at that complex today
      - Never raises — failures are logged and swallowed so the game flow
        is never interrupted

    Parameters
    ----------
    game : FriendlyGame
    """
    try:
        if not game.court_complex:
            logger.info(
                f"FriendlyGame {game.id} has no court_complex — "
                "skipping Billboard presence registration"
            )
            return

        court_complex = game.court_complex
        game_players = game.players.all().select_related('player')

        for game_player in game_players:
            player = game_player.player
            try:
                player_codename_obj = PlayerCodename.objects.get(player=player)
                codename = player_codename_obj.codename

                # Idempotent: skip if already registered at this complex today
                # Use court-local date so Athens courts are not affected by server UTC offset
                already_registered = BillboardEntry.objects.filter(
                    codename=codename,
                    action_type='AT_COURTS',
                    court_complex=court_complex,
                    created_at__date=get_court_local_date(court_complex),
                    is_active=True,
                ).exists()

                if not already_registered:
                    BillboardEntry.objects.create(
                        codename=codename,
                        action_type='AT_COURTS',
                        court_complex=court_complex,
                        message='Auto-registered via friendly game activation',
                        is_active=True,
                    )
                    logger.info(
                        f"Friendly game {game.id}: registered player "
                        f"{player.name} ({codename}) at {court_complex.name}"
                    )
                else:
                    logger.debug(
                        f"Friendly game {game.id}: player {player.name} "
                        f"already at {court_complex.name} today — skipped"
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
