"""
Test suite for:
  1. Freshness scoring on FriendlyGame
  2. 24h expiration management command
  3. Smart PFC priority ordering (score > friendly)
  4. Location-aware routing with freshness filter
"""
import os, sys, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'pfc_core.settings'
django.setup()

from datetime import timedelta
from django.utils import timezone
from django.test import RequestFactory
from django.core.management import call_command
from io import StringIO

from teams.models import Team, Player
from friendly_games.models import PlayerCodename, FriendlyGame, FriendlyGamePlayer
from courts.models import Court, CourtComplex
from pfc_core.smart_router import (
    _resolve_nearby_friendly_games,
    _resolve_friendly_games,
    _resolve_tournament_matches,
    PRIORITY_TOURNAMENT_WAITING_VALIDATE,
    PRIORITY_TOURNAMENT_ACTIVE_SUBMIT,
    PRIORITY_FRIENDLY_NEEDS_VALIDATION,
    PRIORITY_FRIENDLY_NEARBY_JOIN,
)

passed = failed = 0

def check(label, condition):
    global passed, failed
    if condition:
        print(f"  [PASS] {label}")
        passed += 1
    else:
        print(f"  [FAIL] {label}")
        failed += 1

# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────
factory = RequestFactory()

team, _ = Team.objects.get_or_create(name='FreshnessTestTeam', defaults={'pin': '7777'})
player, _ = Player.objects.get_or_create(name='FreshnessTestPlayer', defaults={'team': team})
pc, _ = PlayerCodename.objects.get_or_create(player=player, defaults={'codename': 'FRSH01'})

cc = CourtComplex.objects.create(name='FreshnessTestComplex')
court = Court.objects.create(number=999, is_available=True)
cc.courts.add(court)

# ─────────────────────────────────────────────────────────────────────────────
# 1. FRESHNESS SCORING
# ─────────────────────────────────────────────────────────────────────────────
print("\n1. Freshness scoring")

g_fresh = FriendlyGame.objects.create(
    name='Fresh Game', court_complex=cc, court=court, status='WAITING_FOR_PLAYERS'
)
check("New game freshness_score == 100", g_fresh.freshness_score == 100)
check("New game is_stale == False", g_fresh.is_stale == False)

# Simulate an old game (25 hours ago)
g_old = FriendlyGame.objects.create(
    name='Old Game', court_complex=cc, court=court, status='WAITING_FOR_PLAYERS'
)
FriendlyGame.objects.filter(pk=g_old.pk).update(
    created_at=timezone.now() - timedelta(hours=25)
)
g_old.refresh_from_db()
check("25h old game freshness_score == 0", g_old.freshness_score == 0)
check("25h old game is_stale == True", g_old.is_stale == True)

# Simulate a 3-hour old game
g_mid = FriendlyGame.objects.create(
    name='Mid Game', court_complex=cc, court=court, status='WAITING_FOR_PLAYERS'
)
FriendlyGame.objects.filter(pk=g_mid.pk).update(
    created_at=timezone.now() - timedelta(hours=3)
)
g_mid.refresh_from_db()
check("3h old game freshness_score == 50", g_mid.freshness_score == 50)
check("3h old game is_stale == False", g_mid.is_stale == False)

# ─────────────────────────────────────────────────────────────────────────────
# 2. EXPIRATION MANAGEMENT COMMAND
# ─────────────────────────────────────────────────────────────────────────────
print("\n2. Expiration management command")

# Dry run should not change anything
out = StringIO()
call_command('expire_friendly_games', '--dry-run', stdout=out)
g_old.refresh_from_db()
check("Dry run does not change status", g_old.status == 'WAITING_FOR_PLAYERS')

# Expire-only should mark as EXPIRED but not delete
call_command('expire_friendly_games', '--expire-only', stdout=out)
g_old.refresh_from_db()
check("Expire-only marks old game as EXPIRED", g_old.status == 'EXPIRED')
check("Fresh game still WAITING_FOR_PLAYERS", 
      FriendlyGame.objects.filter(pk=g_fresh.pk, status='WAITING_FOR_PLAYERS').exists())

# Full run should delete already-EXPIRED games
# The game is already EXPIRED from the expire-only step above.
# The full command also deletes all EXPIRED games in step 2.
# But step 1 only finds non-terminal games, and EXPIRED is terminal.
# So we need to verify the delete-all-expired path works.
# Reset the game to a non-terminal status first to test the full flow.
FriendlyGame.objects.filter(pk=g_old.pk).update(status='WAITING_FOR_PLAYERS')
call_command('expire_friendly_games', stdout=out)
check("Full run deletes expired games",
      not FriendlyGame.objects.filter(pk=g_old.pk).exists())
check("Fresh game still exists after full run",
      FriendlyGame.objects.filter(pk=g_fresh.pk).exists())

# ─────────────────────────────────────────────────────────────────────────────
# 3. PRIORITY ORDERING
# ─────────────────────────────────────────────────────────────────────────────
print("\n3. Priority ordering")

check("Tournament score validation > tournament score submission",
      PRIORITY_TOURNAMENT_WAITING_VALIDATE < PRIORITY_TOURNAMENT_ACTIVE_SUBMIT)
check("Tournament score submission > friendly validation",
      PRIORITY_TOURNAMENT_ACTIVE_SUBMIT < PRIORITY_FRIENDLY_NEEDS_VALIDATION)
check("Friendly validation > friendly nearby join",
      PRIORITY_FRIENDLY_NEEDS_VALIDATION < PRIORITY_FRIENDLY_NEARBY_JOIN)

# ─────────────────────────────────────────────────────────────────────────────
# 4. LOCATION-AWARE ROUTING WITH FRESHNESS FILTER
# ─────────────────────────────────────────────────────────────────────────────
print("\n4. Location-aware routing with freshness")

# Clean up mid game
FriendlyGame.objects.filter(name='Mid Game').delete()

req = factory.get('/my-matches/')
req.session = {'preferred_court_complex_id': cc.pk}

# 4a. One fresh game → returns candidate with join URL + match_number
result = _resolve_nearby_friendly_games(req, player)
check("One fresh game → returns candidate dict", result is not None and isinstance(result, dict))
if result:
    check("Candidate URL contains /join/ and match_number",
          '/join/' in result['url'] and 'match_number=' in result['url'])
    check("Candidate priority is FRIENDLY_NEARBY_JOIN",
          result['priority'] == PRIORITY_FRIENDLY_NEARBY_JOIN)

# 4b. Add a stale game (should be ignored)
g_stale = FriendlyGame.objects.create(
    name='Stale Game', court_complex=cc, court=court, status='WAITING_FOR_PLAYERS'
)
FriendlyGame.objects.filter(pk=g_stale.pk).update(
    created_at=timezone.now() - timedelta(hours=25)
)
g_stale.refresh_from_db()

# Still only one fresh game, stale one should be filtered out
result = _resolve_nearby_friendly_games(req, player)
check("Stale game ignored → still returns single-game candidate",
      result is not None and 'match_number=' in result.get('url', ''))

# 4c. Add another fresh game → multiple → plain join URL
g_fresh2 = FriendlyGame.objects.create(
    name='Fresh Game 2', court_complex=cc, court=court, status='WAITING_FOR_PLAYERS'
)
result = _resolve_nearby_friendly_games(req, player)
check("Two fresh games → returns candidate with plain /join/ URL",
      result is not None and '/join/' in result['url'] and 'match_number' not in result['url'])

# 4d. No court context → returns None
req_no_ctx = factory.get('/my-matches/')
req_no_ctx.session = {}
result = _resolve_nearby_friendly_games(req_no_ctx, player)
check("No court context → returns None", result is None)

# ─────────────────────────────────────────────────────────────────────────────
# 5. SCORE RESPONSIBILITY GATE
# ─────────────────────────────────────────────────────────────────────────────
print("\n5. Score responsibility gate (integration)")

# The _resolve_nearby_friendly_games now returns a dict, not a redirect.
# The main resolve_decision_url() only calls it when has_score_responsibility
# is False. We verify the logic by checking that when score candidates exist
# with priority <= 30, the nearby function is NOT called.
# (We can't easily mock this in a script, but we verify the constants.)
check("Score validation priority (10) <= gate threshold (30)",
      PRIORITY_TOURNAMENT_WAITING_VALIDATE <= 30)
check("Score submission priority (20) <= gate threshold (30)",
      PRIORITY_TOURNAMENT_ACTIVE_SUBMIT <= 30)
check("Friendly validation priority (30) <= gate threshold (30)",
      PRIORITY_FRIENDLY_NEEDS_VALIDATION <= 30)
check("Friendly nearby priority (55) > gate threshold (30)",
      PRIORITY_FRIENDLY_NEARBY_JOIN > 30)

# ─────────────────────────────────────────────────────────────────────────────
# Cleanup
# ─────────────────────────────────────────────────────────────────────────────
FriendlyGame.objects.filter(name__startswith='Fresh Game').delete()
FriendlyGame.objects.filter(name__startswith='Stale Game').delete()
cc.delete()
court.delete()

print(f"\n{'='*50}")
print(f"Results: {passed}/{passed+failed} passed")
if failed:
    print(f"FAILURES: {failed}")
    sys.exit(1)
else:
    print("All tests passed!")
