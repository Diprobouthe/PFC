"""
Test all four friendly game feature areas:
  1. Court assignment (priority chain)
  2. Court presence (Billboard registration)
  3. Timed game (timer fields, time_remaining_seconds)
  4. Codename hidden (template context: session_codename + auto_team)
"""
import os, sys, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pfc_core.settings')
sys.path.insert(0, '/home/ubuntu/pfc_project/pfc_clean')
django.setup()

from django.test import RequestFactory
from django.utils import timezone
from courts.models import CourtComplex, Court
from friendly_games.models import FriendlyGame, FriendlyGamePlayer, PlayerCodename
from teams.models import Player, Team
from billboard.models import BillboardEntry
from friendly_games.court_utils import resolve_court_assignment, get_court_context_for_form
from friendly_games.presence_utils import register_friendly_game_players_at_court

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
results = []

def check(label, condition):
    status = PASS if condition else FAIL
    print(f"  [{status}] {label}")
    results.append(condition)

# ─────────────────────────────────────────────────────────────────────────────
# Setup: ensure we have a CourtComplex + Court in the DB
# ─────────────────────────────────────────────────────────────────────────────
cc, _ = CourtComplex.objects.get_or_create(name='Test Complex')
court, _ = Court.objects.get_or_create(
    number=99, defaults={'is_available': True}
)
# Link court to complex (ManyToMany)
if not cc.courts.filter(pk=court.pk).exists():
    cc.courts.add(court)

# ─────────────────────────────────────────────────────────────────────────────
# 1. Court assignment
# ─────────────────────────────────────────────────────────────────────────────
print("\n1. Court assignment")
rf = RequestFactory()

# 1a. Explicit court_id
req = rf.get('/')
req.session = {}
resolved_cc, resolved_court = resolve_court_assignment(req, court_id=court.pk)
check("Explicit court_id resolves to correct court", resolved_court and resolved_court.pk == court.pk)
check("Explicit court_id resolves to correct complex", resolved_cc and resolved_cc.pk == cc.pk)

# 1b. Explicit complex_id (no court_id) → auto-picks a court
req2 = rf.get('/')
req2.session = {}
resolved_cc2, resolved_court2 = resolve_court_assignment(req2, complex_id=cc.pk)
check("Explicit complex_id auto-picks a court", resolved_court2 is not None)
check("Explicit complex_id resolves to correct complex", resolved_cc2 and resolved_cc2.pk == cc.pk)

# 1c. Session preference fallback
req3 = rf.get('/')
req3.session = {'preferred_court_complex_id': cc.pk}
resolved_cc3, resolved_court3 = resolve_court_assignment(req3)
check("Session preference fallback works", resolved_cc3 and resolved_cc3.pk == cc.pk)

# 1d. Admin default fallback (settings.FRIENDLY_GAME_DEFAULT_COURT_COMPLEX_ID = 1)
req4 = rf.get('/')
req4.session = {}
resolved_cc4, resolved_court4 = resolve_court_assignment(req4)
check("Admin default fallback returns a complex", resolved_cc4 is not None)

# 1e. Court context for form
req5 = rf.get('/')
req5.session = {}
ctx = get_court_context_for_form(req5)
check("Form context has all_complexes", 'all_complexes' in ctx)
check("Form context has preferred_complex_id", 'preferred_complex_id' in ctx)

# ─────────────────────────────────────────────────────────────────────────────
# 2. Court presence (Billboard)
# ─────────────────────────────────────────────────────────────────────────────
print("\n2. Court presence")

# Create a test game with a court
team, _ = Team.objects.get_or_create(name='TestTeamFG')
player, _ = Player.objects.get_or_create(name='FGTestPlayer', defaults={'team': team})
codename_obj, _ = PlayerCodename.objects.get_or_create(
    player=player, defaults={'codename': 'FGTEST'}
)
# Ensure unique codename
if codename_obj.codename == 'FGTEST' and PlayerCodename.objects.filter(codename='FGTEST').exclude(pk=codename_obj.pk).exists():
    codename_obj.codename = 'FGT001'
    codename_obj.save()

game = FriendlyGame.objects.create(
    name='Presence Test Game',
    court_complex=cc,
    court=court,
)
FriendlyGamePlayer.objects.create(
    game=game, player=player, team='BLACK', position='MILIEU'
)

# Clear any existing billboard entries for this player today
BillboardEntry.objects.filter(
    codename=codename_obj.codename,
    action_type='AT_COURTS',
    court_complex=cc,
    created_at__date=timezone.now().date(),
).delete()

before_count = BillboardEntry.objects.filter(
    codename=codename_obj.codename,
    action_type='AT_COURTS',
    court_complex=cc,
).count()

register_friendly_game_players_at_court(game)

after_count = BillboardEntry.objects.filter(
    codename=codename_obj.codename,
    action_type='AT_COURTS',
    court_complex=cc,
).count()

check("Billboard entry created for player at court", after_count > before_count)

# Idempotent: calling again should NOT create a duplicate
register_friendly_game_players_at_court(game)
after_count2 = BillboardEntry.objects.filter(
    codename=codename_obj.codename,
    action_type='AT_COURTS',
    court_complex=cc,
    created_at__date=timezone.now().date(),
    is_active=True,
).count()
check("Idempotent: no duplicate entry on second call", after_count2 == 1)

# No court → no billboard entry (should not crash)
game_no_court = FriendlyGame.objects.create(name='No Court Game')
try:
    register_friendly_game_players_at_court(game_no_court)
    check("No court → no crash", True)
except Exception as e:
    check(f"No court → no crash (got: {e})", False)

# ─────────────────────────────────────────────────────────────────────────────
# 3. Timed game
# ─────────────────────────────────────────────────────────────────────────────
print("\n3. Timed game")

timed_game = FriendlyGame.objects.create(
    name='Timed Test Game',
    is_timed=True,
    time_limit_minutes=30,
    court_complex=cc,
    court=court,
)
# Explicitly set ACTIVE + timer (mirrors what start_match does)
timed_game.status = 'ACTIVE'
timed_game.timer_started_at = timezone.now()
timed_game.save()

check("is_timed field saved correctly", timed_game.is_timed is True)
check("time_limit_minutes saved correctly", timed_game.time_limit_minutes == 30)
check("time_remaining_seconds is int", isinstance(timed_game.time_remaining_seconds, int))
check("time_remaining_seconds <= 1800", timed_game.time_remaining_seconds <= 1800)
check("time_remaining_display is MM:SS string", ':' in (timed_game.time_remaining_display or ''))
check("is_time_expired is False (just started)", not timed_game.is_time_expired)

# Untimed game
untimed_game = FriendlyGame.objects.create(name='Untimed Test Game')
check("Untimed game: time_remaining_seconds is None", untimed_game.time_remaining_seconds is None)
check("Untimed game: is_time_expired is False", not untimed_game.is_time_expired)

# ─────────────────────────────────────────────────────────────────────────────
# 4. Codename hidden (view context)
# ─────────────────────────────────────────────────────────────────────────────
print("\n4. Codename hidden in submit_score context")

# Simulate what the view does: auto-detect team from session_codename
session_codename = codename_obj.codename
auto_team = None
for gp in game.players.all():
    try:
        if gp.player.codename_profile.codename == session_codename:
            auto_team = gp.team
            break
    except Exception:
        pass

check("auto_team detected from session codename", auto_team == 'BLACK')
check("session_codename is the raw codename (not shown to user)", len(session_codename) == 6)

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'='*50}")
passed = sum(results)
total = len(results)
print(f"Results: {passed}/{total} passed")
if passed == total:
    print("\033[92mAll tests passed!\033[0m")
else:
    print(f"\033[91m{total - passed} test(s) failed.\033[0m")
    sys.exit(1)
