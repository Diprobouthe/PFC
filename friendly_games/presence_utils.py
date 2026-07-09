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

Post-game grace entries:
  When a game ends, a short-lived 'post_game' entry (30 minutes) is created
  for each player so they remain visible/available at the Court Complex for
  quick rematch or new-game creation.  These entries carry:
    presence_source = 'post_game'
    game_ref        = 'friendly:<game.id>'
    expires_at      = now + 30 minutes

Called from:
  - start_game()        → register all players when game goes ACTIVE
  - game ends/validates → deactivate_friendly_game_presence(game)
  - game cancelled      → deactivate_friendly_game_presence(game)
  - game expires        → deactivate_friendly_game_presence(game)
"""

import logging
from datetime import timedelta

from django.utils import timezone

from billboard.models import BillboardEntry
from friendly_games.models import PlayerCodename
from courts.timezone_utils import get_court_local_date

logger = logging.getLogger(__name__)

# How long players remain visible at the court after a game ends.
POST_GAME_GRACE_MINUTES = 30


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


# ── Deactivation + post-game grace ────────────────────────────────────────────

def deactivate_friendly_game_presence(game):
    """
    Deactivate all AT_COURTS entries that were created for *game* and replace
    them with short-lived 'post_game' grace entries (30 minutes).

    Behaviour:
    - Deactivates the game-specific 'friendly_game' entries immediately.
    - For each player, creates a new 'post_game' entry that expires in
      POST_GAME_GRACE_MINUTES minutes, so the player remains visible at the
      Court Complex for quick rematch / new game creation.
    - Skips creating a grace entry if the player already has an active
      'post_game' entry at the same court (idempotent).
    - Only touches entries tagged with game_ref='friendly:<game.id>'.
    - Manual check-ins and other games' entries are never affected.
    - Historical records are preserved (is_active=False, not deleted).

    Safe to call multiple times — idempotent.
    Never raises.
    """
    try:
        game_ref = f"friendly:{game.id}"

        # Collect the active entries before deactivating so we know who to grace.
        active_entries = list(
            BillboardEntry.objects.filter(
                action_type='AT_COURTS',
                game_ref=game_ref,
                is_active=True,
            ).select_related('court_complex')
        )

        # Deactivate game-specific entries.
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

        # Create post-game grace entries for each player.
        _create_post_game_grace_entries(active_entries, game_ref)

    except Exception as exc:
        logger.error(
            f"Error deactivating presence for friendly game {game.id}: {exc}"
        )


# ── Internal helper ───────────────────────────────────────────────────────────

def _create_post_game_grace_entries(active_entries, game_ref):
    """
    Given a list of just-deactivated BillboardEntry rows, create a 30-minute
    'post_game' grace entry for each unique (codename, court_complex) pair.

    Idempotent: skips if an active post_game entry already exists for that
    player at that court (e.g. from a previous game that ended moments ago).
    """
    if not active_entries:
        return

    grace_expiry = timezone.now() + timedelta(minutes=POST_GAME_GRACE_MINUTES)
    seen = set()

    for entry in active_entries:
        key = (entry.codename, entry.court_complex_id)
        if key in seen:
            continue
        seen.add(key)

        # Skip if an active post_game entry for THIS SAME game already exists.
        # We intentionally do NOT refresh entries from other games — each game
        # gets its own 30-min grace window, and refreshing an old entry from a
        # different game would extend stale presence incorrectly.
        already_has_grace = BillboardEntry.objects.filter(
            codename=entry.codename,
            action_type='AT_COURTS',
            court_complex=entry.court_complex,
            presence_source=BillboardEntry.PRESENCE_SOURCE_POST_GAME,
            game_ref=game_ref,
            is_active=True,
        ).exists()

        if already_has_grace:
            # Refresh the expiry only for the entry from THIS game.
            BillboardEntry.objects.filter(
                codename=entry.codename,
                action_type='AT_COURTS',
                court_complex=entry.court_complex,
                presence_source=BillboardEntry.PRESENCE_SOURCE_POST_GAME,
                game_ref=game_ref,
                is_active=True,
            ).update(expires_at=grace_expiry)
            logger.debug(
                f"Post-game grace: refreshed expiry for {entry.codename} "
                f"at {entry.court_complex.name} (game_ref={game_ref})"
            )
        else:
            BillboardEntry.objects.create(
                codename=entry.codename,
                action_type='AT_COURTS',
                court_complex=entry.court_complex,
                message='Post-game availability (30 min)',
                is_active=True,
                presence_source=BillboardEntry.PRESENCE_SOURCE_POST_GAME,
                game_ref=game_ref,
                expires_at=grace_expiry,
            )
            logger.info(
                f"Post-game grace: created 30-min entry for {entry.codename} "
                f"at {entry.court_complex.name} (game_ref={game_ref})"
            )
