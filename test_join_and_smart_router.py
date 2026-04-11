"""
Test both patches:
  1. Codename hidden on join page
  2. Smart PFC court-complex-aware friendly game routing
"""
import os, sys, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'pfc_core.settings'
django.setup()

from django.utils import timezone
from django.test import RequestFactory
from teams.models import Team, Player
from friendly_games.models import PlayerCodename, FriendlyGame, FriendlyGamePlayer
from courts.models import Court, CourtComplex
from pfc_core.smart_router import _resolve_nearby_friendly_games

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
# Setup — use a dedicated complex that has NO pre-existing games
# ─────────────────────────────────────────────────────────────────────────────
factory = RequestFactory()

team, _ = Team.objects.get_or_create(name='TestSwapTeam99', defaults={'pin': '9999'})
player, _ = Player.objects.get_or_create(name='TestRouterPlayer', defaults={'team': team})
pc, _ = PlayerCodename.objects.get_or_create(player=player, defaults={'codename': 'RTST01'})

# Create a FRESH complex with no games
cc_test = CourtComplex.objects.create(name='IsolatedTestComplex')
court_test = Court.objects.create(number=777, is_available=True)
cc_test.courts.add(court_test)

# A second complex for the "different complex" test
cc_other = CourtComplex.objects.create(name='OtherIsolatedComplex')

# ─────────────────────────────────────────────────────────────────────────────
# 1. Codename hidden on join page template
# ─────────────────────────────────────────────────────────────────────────────
print("\n1. Codename hidden on join page")

template_path = os.path.join(
    os.path.dirname(__file__),
    'friendly_games/templates/friendly_games/join_game.html'
)
with open(template_path, 'r') as f:
    content = f.read()

check("No visible codename label", 'Player Codename (Optional)' not in content)
check("No type=text codename input",
      'type="text"' not in content.split('id="codename"')[0].split('\n')[-1]
      if 'id="codename"' in content else False)
check("Hidden codename input exists", 'type="hidden" id="codename" name="codename"' in content)
check("No codename help text", 'Enter your codename to record statistics' not in content)

# ─────────────────────────────────────────────────────────────────────────────
# 2. Smart PFC — no nearby games → returns None (fall through)
# ─────────────────────────────────────────────────────────────────────────────
print("\n2. Smart PFC — no nearby games at isolated complex")

req = factory.get('/my-matches/')
req.session = {'preferred_court_complex_id': cc_test.pk}

result = _resolve_nearby_friendly_games(req, player)
check("No nearby games → returns None", result is None)

# ─────────────────────────────────────────────────────────────────────────────
# 3. Smart PFC — exactly one joinable game at same complex
# ─────────────────────────────────────────────────────────────────────────────
print("\n3. Smart PFC — one joinable game at same complex")

game1 = FriendlyGame.objects.create(
    name='RouterTest Game 1',
    court_complex=cc_test,
    court=court_test,
    status='WAITING_FOR_PLAYERS',
)

result = _resolve_nearby_friendly_games(req, player)
check("Returns redirect (not None)", result is not None)
if result is not None:
    check("Redirects to game detail URL", f'/{game1.id}/' in result.url)
else:
    check("Redirects to game detail URL", False)

# ─────────────────────────────────────────────────────────────────────────────
# 4. Smart PFC — player already joined → should NOT count as joinable
# ─────────────────────────────────────────────────────────────────────────────
print("\n4. Smart PFC — player already joined game")

FriendlyGamePlayer.objects.create(
    game=game1, player=player, team='BLACK', position='MILIEU'
)

result = _resolve_nearby_friendly_games(req, player)
check("Player already in game → returns None (not joinable)", result is None)

# Clean up participation
FriendlyGamePlayer.objects.filter(game=game1, player=player).delete()

# ─────────────────────────────────────────────────────────────────────────────
# 5. Smart PFC — multiple joinable games → route to join page
# ─────────────────────────────────────────────────────────────────────────────
print("\n5. Smart PFC — multiple joinable games at same complex")

game2 = FriendlyGame.objects.create(
    name='RouterTest Game 2',
    court_complex=cc_test,
    court=court_test,
    status='WAITING_FOR_PLAYERS',
)

result = _resolve_nearby_friendly_games(req, player)
check("Returns redirect (not None)", result is not None)
if result is not None:
    check("Redirects to join page", '/join/' in result.url)
else:
    check("Redirects to join page", False)

# ─────────────────────────────────────────────────────────────────────────────
# 6. Smart PFC — no court complex in session → returns None
# ─────────────────────────────────────────────────────────────────────────────
print("\n6. Smart PFC — no court complex in session")

req_no_ctx = factory.get('/my-matches/')
req_no_ctx.session = {}

result = _resolve_nearby_friendly_games(req_no_ctx, player)
check("No court context → returns None", result is None)

# ─────────────────────────────────────────────────────────────────────────────
# 7. Smart PFC — game at different complex → not counted
# ─────────────────────────────────────────────────────────────────────────────
print("\n7. Smart PFC — game at different complex")

# Delete the games at cc_test first
FriendlyGame.objects.filter(name__startswith='RouterTest').delete()

game3 = FriendlyGame.objects.create(
    name='RouterTest Game 3',
    court_complex=cc_other,
    court=court_test,
    status='WAITING_FOR_PLAYERS',
)

# Session still points to cc_test (not cc_other)
result = _resolve_nearby_friendly_games(req, player)
check("Game at different complex → returns None", result is None)

# ─────────────────────────────────────────────────────────────────────────────
# Cleanup
# ─────────────────────────────────────────────────────────────────────────────
FriendlyGame.objects.filter(name__startswith='RouterTest').delete()
cc_test.delete()
cc_other.delete()
court_test.delete()

print(f"\n{'='*50}")
print(f"Results: {passed}/{passed+failed} passed")
if failed:
    print(f"FAILURES: {failed}")
    sys.exit(1)
else:
    print("All tests passed!")
