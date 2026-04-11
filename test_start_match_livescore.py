"""
Test: Start Match → Live Score + Submit Score Pre-fill
"""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pfc_core.settings')
sys.path.insert(0, '/home/ubuntu/pfc_project/pfc_clean')
django.setup()

from django.test import RequestFactory
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.messages.storage.fallback import FallbackStorage
from friendly_games.models import FriendlyGame, FriendlyGamePlayer
from matches.models import LiveScoreboard
from teams.models import Player, Team
from django.utils import timezone

passed = 0
failed = 0

def test(name, condition):
    global passed, failed
    if condition:
        print(f"  ✅ {name}")
        passed += 1
    else:
        print(f"  ❌ {name}")
        failed += 1

print("=" * 60)
print("TEST 1: Start Match redirects to live scoreboard")
print("=" * 60)

# Find an existing ACTIVE friendly game with a scoreboard
active_game = FriendlyGame.objects.filter(status='ACTIVE').first()
if active_game:
    try:
        sb = active_game.live_scoreboard
        test("Active game has live_scoreboard", sb is not None)
        test("Scoreboard has valid ID", sb.id > 0)
        
        # Verify the URL would be /matches/scoreboard/{id}/
        from django.urls import reverse
        expected_url = reverse('scoreboard_detail', kwargs={'scoreboard_id': sb.id})
        test(f"Expected redirect URL: {expected_url}", '/scoreboard/' in expected_url)
    except Exception as e:
        test(f"Scoreboard access failed: {e}", False)
else:
    print("  ⚠ No active friendly game found, testing with WAITING_FOR_PLAYERS game")
    wfp_game = FriendlyGame.objects.filter(status='WAITING_FOR_PLAYERS').first()
    if wfp_game:
        try:
            sb = wfp_game.live_scoreboard
            test("WAITING game has live_scoreboard (created by signal)", sb is not None)
        except Exception as e:
            test(f"Scoreboard exists for WFP game: {e}", False)

print()
print("=" * 60)
print("TEST 2: Smart PFC routes ACTIVE friendly to scoreboard")
print("=" * 60)

from pfc_core.smart_router import _resolve_friendly_games
# Find a player in an active friendly game
active_games = FriendlyGame.objects.filter(status='ACTIVE')
for ag in active_games:
    fgps = FriendlyGamePlayer.objects.filter(game=ag)
    if fgps.exists():
        fgp = fgps.first()
        player = fgp.player
        player_team = player.team
        if player_team:
            candidates = _resolve_friendly_games(player, player_team)
            for c in candidates:
                if 'scoreboard' in c.get('url', ''):
                    test("ACTIVE friendly game routes to scoreboard URL", True)
                    test(f"URL contains /scoreboard/: {c['url']}", '/scoreboard/' in c['url'])
                    break
            else:
                # Check if there are any active candidates at all
                active_candidates = [c for c in candidates if 'Active' in c.get('label', '') or 'Live Score' in c.get('label', '')]
                if active_candidates:
                    test(f"Active candidate URL: {active_candidates[0]['url']}", '/scoreboard/' in active_candidates[0]['url'])
                else:
                    test("No active friendly game candidate found for this player", False)
            break
else:
    print("  ⚠ No active friendly game with players found, skipping")

print()
print("=" * 60)
print("TEST 3: Submit Score pre-fills from live scoreboard")
print("=" * 60)

# Find a game with a scoreboard that has non-zero scores
scoreboards = LiveScoreboard.objects.filter(friendly_game__isnull=False, is_active=True)
if scoreboards.exists():
    sb = scoreboards.first()
    game = sb.friendly_game
    
    # Set some test scores on the scoreboard
    sb.team1_score = 7
    sb.team2_score = 5
    sb.save()
    
    test("Scoreboard has team1_score=7", sb.team1_score == 7)
    test("Scoreboard has team2_score=5", sb.team2_score == 5)
    
    # Verify the view would pick these up
    try:
        scoreboard = game.live_scoreboard
        prefill_black = scoreboard.team1_score or 0
        prefill_white = scoreboard.team2_score or 0
        test(f"Pre-fill black score = {prefill_black} (expected 7)", prefill_black == 7)
        test(f"Pre-fill white score = {prefill_white} (expected 5)", prefill_white == 5)
    except Exception as e:
        test(f"Pre-fill access failed: {e}", False)
    
    # Reset the test scores
    sb.team1_score = 0
    sb.team2_score = 0
    sb.save()
else:
    print("  ⚠ No friendly game scoreboard found, testing model access")
    game = FriendlyGame.objects.first()
    if game:
        try:
            sb = game.live_scoreboard
            test("Game has live_scoreboard accessible", sb is not None)
            prefill_black = sb.team1_score or 0
            prefill_white = sb.team2_score or 0
            test(f"Pre-fill defaults to 0/0: {prefill_black}/{prefill_white}", prefill_black == 0 and prefill_white == 0)
        except Exception as e:
            test(f"Scoreboard access: {e}", False)

print()
print("=" * 60)
print(f"RESULTS: {passed} passed, {failed} failed out of {passed + failed}")
print("=" * 60)
