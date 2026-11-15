"""Regression coverage for Friendly expiry and creator cancellation."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from billboard.models import BillboardEntry
from courts.models import CourtComplex
from friendly_games.expiration import expire_stale_friendly_games
from friendly_games.models import FriendlyGame, PlayerCodename
from teams.models import Player, Team


class FriendlyExpiryAndCancelTests(TestCase):
    def setUp(self):
        team = Team.objects.create(name='Expiry Test Team')
        self.complex = CourtComplex.objects.create(name='Expiry Test Courts')
        self.creator = Player.objects.create(name='Expiry Creator', team=team)
        self.other = Player.objects.create(name='Expiry Other', team=team)
        self.codename = PlayerCodename.objects.create(
            player=self.creator, codename='EXPCR1'
        )
        PlayerCodename.objects.create(player=self.other, codename='EXPOT1')

    def make_game(self, *, status='ACTIVE', age_minutes=0):
        game = FriendlyGame.objects.create(
            name='Expiry Test Friendly', creator_player=self.creator
        )
        started = timezone.now() - timedelta(minutes=age_minutes)
        FriendlyGame.objects.filter(pk=game.pk).update(
            status=status, started_at=started
        )
        game.refresh_from_db()
        return game

    def test_started_game_stays_active_at_149_minutes_even_with_zero_score(self):
        game = self.make_game(age_minutes=149)
        expire_stale_friendly_games()
        game.refresh_from_db()
        self.assertEqual(game.status, 'ACTIVE')

    def test_started_game_expires_after_150_minutes_without_score(self):
        game = self.make_game(age_minutes=151)
        expire_stale_friendly_games()
        game.refresh_from_db()
        self.assertEqual(game.status, 'CANCELLED')

    def test_started_game_expires_after_150_minutes_with_score(self):
        game = self.make_game(age_minutes=151)
        game.black_team_score = 6
        game.white_team_score = 4
        game.save(update_fields=['black_team_score', 'white_team_score'])
        expire_stale_friendly_games()
        game.refresh_from_db()
        self.assertEqual(game.status, 'CANCELLED')

    def test_recent_pending_validation_not_cancelled(self):
        game = self.make_game(status='PENDING_VALIDATION', age_minutes=151)
        expire_stale_friendly_games()
        game.refresh_from_db()
        self.assertEqual(game.status, 'PENDING_VALIDATION')

    def test_expiry_does_not_grant_post_game_presence(self):
        game = self.make_game(age_minutes=151)
        BillboardEntry.objects.create(
            codename=self.codename.codename, action_type='AT_COURTS',
            presence_source=BillboardEntry.PRESENCE_SOURCE_FRIENDLY,
            game_ref=f'friendly:{game.pk}', is_active=True,
            court_complex=self.complex,
        )
        expire_stale_friendly_games()
        self.assertFalse(BillboardEntry.objects.filter(
            game_ref=f'friendly:{game.pk}', is_active=True
        ).exists())

    def test_creator_can_cancel_active_game(self):
        game = self.make_game()
        session = self.client.session
        session['player_codename'] = self.codename.codename
        session['session_active'] = True
        session.save()
        response = self.client.post(reverse('friendly_games:cancel_game', args=[game.pk]))
        self.assertEqual(response.status_code, 302)
        game.refresh_from_db()
        self.assertEqual(game.status, 'CANCELLED')

    def test_other_player_cannot_cancel(self):
        game = self.make_game()
        session = self.client.session
        session['player_codename'] = 'EXPOT1'
        session['session_active'] = True
        session.save()
        self.client.post(reverse('friendly_games:cancel_game', args=[game.pk]))
        game.refresh_from_db()
        self.assertEqual(game.status, 'ACTIVE')

    def test_get_cannot_cancel(self):
        game = self.make_game()
        self.client.get(reverse('friendly_games:cancel_game', args=[game.pk]))
        game.refresh_from_db()
        self.assertEqual(game.status, 'ACTIVE')
