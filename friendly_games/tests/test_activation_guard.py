from django.test import TestCase
from django.urls import reverse

from friendly_games.models import (
    FriendlyGame,
    FriendlyGameActivationConflict,
    FriendlyGamePlayer,
    FriendlyGameResult,
    PlayerCodename,
)
from teams.models import Player, Team


class FriendlyActivationGuardTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name='Activation Guard Team')
        self.player_one = Player.objects.create(name='Player One', team=self.team)
        self.player_two = Player.objects.create(name='Player Two', team=self.team)
        PlayerCodename.objects.create(player=self.player_one, codename='PLYR01')

    def make_game(self, name, status='WAITING_FOR_PLAYERS'):
        game = FriendlyGame.objects.create(name=name, creator_player=self.player_one)
        if status != 'WAITING_FOR_PLAYERS':
            game.status = status
            game.save()
        FriendlyGamePlayer.objects.create(
            game=game,
            player=self.player_one,
            team='BLACK',
            position='MILIEU',
        )
        FriendlyGamePlayer.objects.create(
            game=game,
            player=self.player_two,
            team='WHITE',
            position='MILIEU',
        )
        return game

    def test_waiting_games_may_share_players(self):
        first_game = self.make_game('First setup')
        second_game = self.make_game('Second setup')

        self.assertEqual(first_game.status, 'WAITING_FOR_PLAYERS')
        self.assertEqual(second_game.status, 'WAITING_FOR_PLAYERS')

    def test_second_game_is_blocked_when_shared_player_is_active_elsewhere(self):
        active_game = self.make_game('Active game')
        waiting_game = self.make_game('Blocked game')
        active_game.activate()

        with self.assertRaises(FriendlyGameActivationConflict) as raised:
            waiting_game.activate()

        self.assertEqual(raised.exception.player_names, ('Player One', 'Player Two'))
        waiting_game.refresh_from_db()
        self.assertEqual(waiting_game.status, 'WAITING_FOR_PLAYERS')

    def test_second_game_is_blocked_when_shared_player_is_pending_validation_elsewhere(self):
        unresolved_game = self.make_game('Unresolved game')
        waiting_game = self.make_game('Blocked game')
        unresolved_game.status = 'PENDING_VALIDATION'
        unresolved_game.save()

        with self.assertRaises(FriendlyGameActivationConflict):
            waiting_game.activate()

        waiting_game.refresh_from_db()
        self.assertEqual(waiting_game.status, 'WAITING_FOR_PLAYERS')

    def test_terminal_friendly_does_not_block_a_new_activation(self):
        completed_game = self.make_game('Completed game')
        waiting_game = self.make_game('New game')
        completed_game.status = 'COMPLETED'
        completed_game.save()

        waiting_game.activate()

        waiting_game.refresh_from_db()
        self.assertEqual(waiting_game.status, 'ACTIVE')

    def test_start_match_route_reports_an_active_or_unresolved_conflict(self):
        active_game = self.make_game('Active game')
        waiting_game = self.make_game('Blocked start')
        active_game.activate()
        session = self.client.session
        session['player_codename'] = 'PLYR01'
        session['session_active'] = True
        session.save()

        response = self.client.get(
            reverse('friendly_games:start_match', args=[waiting_game.id]),
            follow=True,
        )

        waiting_game.refresh_from_db()
        self.assertEqual(waiting_game.status, 'WAITING_FOR_PLAYERS')
        self.assertContains(response, 'already participating in another active or unresolved Friendly Game')

    def test_direct_status_transition_is_also_protected(self):
        active_game = self.make_game('Active game')
        waiting_game = self.make_game('Direct-save game')
        active_game.activate()

        waiting_game.status = 'ACTIVE'
        with self.assertRaises(FriendlyGameActivationConflict):
            waiting_game.save()

        waiting_game.refresh_from_db()
        self.assertEqual(waiting_game.status, 'WAITING_FOR_PLAYERS')

    def test_disputed_result_cannot_reopen_while_players_are_active_elsewhere(self):
        disputed_game = self.make_game('Disputed game')
        other_game = self.make_game('Other active game')
        other_game.activate()
        disputed_game.status = 'PENDING_VALIDATION'
        disputed_game.save()
        result = FriendlyGameResult.objects.create(
            game=disputed_game,
            submitted_by_team='BLACK',
        )

        with self.assertRaises(FriendlyGameActivationConflict):
            result.validate_result('WHITE', 'disagree')

        disputed_game.refresh_from_db()
        self.assertEqual(disputed_game.status, 'PENDING_VALIDATION')
        self.assertTrue(FriendlyGameResult.objects.filter(pk=result.pk).exists())
