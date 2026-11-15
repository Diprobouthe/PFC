"""Regression: Smart navigation must not perform global Friendly expiration."""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from pfc_core.smart_router import resolve_decision_url


class SmartRouterNoGlobalExpirationTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_anonymous_smart_click_does_not_expire_unrelated_friendlies(self):
        request = self.factory.get('/my-matches/')
        request.session = {}
        with (patch('friendly_games.expiration.expire_stale_friendly_games') as expire,
              patch('pfc_core.smart_router.render') as render):
            resolve_decision_url(request)
        expire.assert_not_called()
        self.assertTrue(render.called)

    def test_authenticated_smart_click_preserves_direct_routing_without_expiration(self):
        request = self.factory.get('/my-matches/')
        request.session = {'player_codename': 'TEST001'}
        player = SimpleNamespace(pk=1, id=1)
        player_codename = SimpleNamespace(player=player)
        candidate = {'priority': 55, 'url': '/matches/scoreboard/123/', 'label': 'Live'}
        with (patch('friendly_games.expiration.expire_stale_friendly_games') as expire,
              patch('pfc_core.smart_router.PlayerCodename.objects.get', return_value=player_codename),
              patch('pfc_core.smart_router._resolve_tournament_matches', return_value=[candidate]),
              patch('pfc_core.smart_router._resolve_friendly_games', return_value=[]),
              patch('pfc_core.smart_router._resolve_nearby_friendly_games', return_value=None)):
            response = resolve_decision_url(request)
        expire.assert_not_called()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], candidate['url'])
