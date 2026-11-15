"""Focused Smart identity, Billboard presence and QR isolation regressions."""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from pfc_core.smart_router import _session_player, _get_player_court_complex


class SmartIdentityPresenceTests(SimpleTestCase):
    def setUp(self):
        self.request = RequestFactory().get('/my-matches/')
        self.request.session = {'player_codename': 'ABC123'}

    def test_existing_session_lazily_records_player_id(self):
        player = SimpleNamespace(id=17)
        pc = SimpleNamespace(player_id=17, player=player)
        with patch('pfc_core.smart_router.PlayerCodename.objects.select_related') as related:
            related.return_value.get.return_value = pc
            self.assertIs(_session_player(self.request), player)
        self.assertEqual(self.request.session['smart_router_player_id'], 17)
        self.assertEqual(self.request.session['smart_router_player_codename'], 'ABC123')

    def test_repeated_smart_identity_uses_player_id_not_codename_lookup(self):
        self.request.session.update(smart_router_player_id=17,
                                    smart_router_player_codename='ABC123')
        player = SimpleNamespace(id=17)
        with patch('pfc_core.smart_router.Player.objects.filter') as players, \
             patch('pfc_core.smart_router.PlayerCodename.objects.select_related') as codename_lookup:
            players.return_value.first.return_value = player
            self.assertIs(_session_player(self.request), player)
            codename_lookup.assert_not_called()

    def test_codename_change_does_not_reuse_old_player_id(self):
        self.request.session.update(smart_router_player_id=17,
                                    smart_router_player_codename='DIFFERENT')
        pc = SimpleNamespace(player_id=29, player=SimpleNamespace(id=29))
        with patch('pfc_core.smart_router.Player.objects.filter') as players, \
             patch('pfc_core.smart_router.PlayerCodename.objects.select_related') as related:
            related.return_value.get.return_value = pc
            self.assertEqual(_session_player(self.request).id, 29)
            players.assert_not_called()
        self.assertEqual(self.request.session['smart_router_player_id'], 29)

    def test_court_comes_from_valid_billboard_before_session_preference(self):
        self.request.session['preferred_court_complex_id'] = 5
        with patch('pfc_core.smart_router.current_player_court_presence') as current:
            current.return_value.values_list.return_value.first.return_value = 11
            self.assertEqual(_get_player_court_complex(self.request, None), 11)
            current.assert_called_once_with('ABC123')

    def test_no_current_presence_falls_back_to_existing_preference(self):
        self.request.session['preferred_court_complex_id'] = 5
        with patch('pfc_core.smart_router.current_player_court_presence') as current:
            current.return_value.values_list.return_value.first.return_value = None
            self.assertEqual(_get_player_court_complex(self.request, None), 5)
