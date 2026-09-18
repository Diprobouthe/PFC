"""
Test timer visibility across all patched templates.
Verifies that timer partials are included in the right templates
and that model properties work correctly.
"""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pfc_core.settings')
sys.path.insert(0, '/home/ubuntu/pfc_project/pfc_clean')
django.setup()

from datetime import timedelta
from django.utils import timezone

passed = 0
failed = 0

def test(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"  PASS  {name}")
        passed += 1
    else:
        print(f"  FAIL  {name} — {detail}")
        failed += 1

# ─── 1. Model timer properties ───
print("\n=== 1. FriendlyGame timer properties ===")
from friendly_games.models import FriendlyGame

fg = FriendlyGame()
fg.is_timed = True
fg.time_limit_minutes = 45
fg.status = 'ACTIVE'
fg.timer_started_at = timezone.now() - timedelta(minutes=10)

test("time_remaining_seconds > 0 for active timed game",
     fg.time_remaining_seconds is not None and fg.time_remaining_seconds > 0,
     f"got {fg.time_remaining_seconds}")

test("timer_total_seconds = 2700 for 45min game",
     fg.timer_total_seconds == 2700,
     f"got {fg.timer_total_seconds}")

test("is_time_expired = False when 35min remain",
     fg.is_time_expired == False,
     f"got {fg.is_time_expired}")

# Expired game
fg2 = FriendlyGame()
fg2.is_timed = True
fg2.time_limit_minutes = 10
fg2.status = 'ACTIVE'
fg2.timer_started_at = timezone.now() - timedelta(minutes=15)

test("is_time_expired = True when timer exceeded",
     fg2.is_time_expired == True,
     f"got {fg2.is_time_expired}")

test("time_remaining_seconds = 0 when expired",
     fg2.time_remaining_seconds == 0,
     f"got {fg2.time_remaining_seconds}")

# Untimed game
fg3 = FriendlyGame()
fg3.is_timed = False
fg3.status = 'ACTIVE'

test("time_remaining_seconds = None for untimed game",
     fg3.time_remaining_seconds is None,
     f"got {fg3.time_remaining_seconds}")

test("timer_total_seconds = None for untimed game",
     fg3.timer_total_seconds is None,
     f"got {fg3.timer_total_seconds}")

# ─── 2. Match timer properties ───
print("\n=== 2. Match timer_total_seconds property ===")
from matches.models import Match

m = Match()
m.time_limit_minutes = 60

test("Match.timer_total_seconds = 3600 for 60min match",
     m.timer_total_seconds == 3600,
     f"got {m.timer_total_seconds}")

m2 = Match()
m2.time_limit_minutes = None

test("Match.timer_total_seconds = None when no limit",
     m2.timer_total_seconds is None,
     f"got {m2.timer_total_seconds}")

# ─── 3. Template partial files exist ───
print("\n=== 3. Timer partial templates exist ===")
partials_dir = '/home/ubuntu/pfc_project/pfc_clean/templates/partials'

for name in ['timer_card.html', 'timer_bar.html', 'timer_badge.html', 'timer_countdown_js.html']:
    path = os.path.join(partials_dir, name)
    test(f"{name} exists", os.path.isfile(path), f"not found at {path}")

# ─── 4. Timer includes in templates ───
print("\n=== 4. Timer includes in patched templates ===")

templates_to_check = {
    'friendly game_detail': '/home/ubuntu/pfc_project/pfc_clean/friendly_games/templates/friendly_games/game_detail.html',
    'friendly submit_score': '/home/ubuntu/pfc_project/pfc_clean/friendly_games/templates/friendly_games/submit_score.html',
    'friendly validate_result': '/home/ubuntu/pfc_project/pfc_clean/friendly_games/templates/friendly_games/validate_result.html',
    'tournament match_submit_result': '/home/ubuntu/pfc_project/pfc_clean/templates/matches/match_submit_result.html',
    'tournament match_validate_result': '/home/ubuntu/pfc_project/pfc_clean/templates/matches/match_validate_result.html',
    'match_status_table (spectator)': '/home/ubuntu/pfc_project/pfc_clean/templates/matches/partials/match_status_table.html',
    'tournament_detail': '/home/ubuntu/pfc_project/pfc_clean/templates/tournaments/tournament_detail.html',
    'tournament_overview': '/home/ubuntu/pfc_project/pfc_clean/tournaments/templates/tournaments/tournament_overview.html',
}

for label, path in templates_to_check.items():
    with open(path, 'r') as f:
        content = f.read()
    has_timer = 'timer_' in content or 'timer-badge' in content or 'timer-text' in content
    test(f"{label} has timer reference", has_timer, "no timer_* reference found")

# ─── 5. Timer countdown JS in templates ───
print("\n=== 5. Countdown JS in patched templates ===")

countdown_templates = {
    'friendly game_detail': '/home/ubuntu/pfc_project/pfc_clean/friendly_games/templates/friendly_games/game_detail.html',
    'friendly submit_score': '/home/ubuntu/pfc_project/pfc_clean/friendly_games/templates/friendly_games/submit_score.html',
    'friendly validate_result': '/home/ubuntu/pfc_project/pfc_clean/friendly_games/templates/friendly_games/validate_result.html',
    'tournament match_submit_result': '/home/ubuntu/pfc_project/pfc_clean/templates/matches/match_submit_result.html',
    'tournament match_validate_result': '/home/ubuntu/pfc_project/pfc_clean/templates/matches/match_validate_result.html',
    'match_status_table (spectator)': '/home/ubuntu/pfc_project/pfc_clean/templates/matches/partials/match_status_table.html',
    'tournament_detail': '/home/ubuntu/pfc_project/pfc_clean/templates/tournaments/tournament_detail.html',
    'tournament_overview': '/home/ubuntu/pfc_project/pfc_clean/tournaments/templates/tournaments/tournament_overview.html',
}

for label, path in countdown_templates.items():
    with open(path, 'r') as f:
        content = f.read()
    has_countdown = 'timer_countdown_js' in content or 'remaining' in content or 'setInterval(tick' in content
    test(f"{label} has countdown JS", has_countdown, "no countdown JS found")

# ─── 6. match_detail.html still has its original timer ───
print("\n=== 6. Original match_detail timer preserved ===")
md_path = '/home/ubuntu/pfc_project/pfc_clean/templates/matches/match_detail.html'
with open(md_path, 'r') as f:
    md_content = f.read()
test("match_detail.html still has timer", 'time_remaining' in md_content or 'countdown' in md_content.lower(),
     "original timer may have been removed")

# ─── Summary ───
print(f"\n{'='*50}")
print(f"RESULTS: {passed} passed, {failed} failed out of {passed+failed}")
if failed == 0:
    print("ALL TESTS PASSED")
else:
    print("SOME TESTS FAILED")
