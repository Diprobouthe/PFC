from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from friendly_games.models import PlayerCodename
from matches.forms import MatchActivationForm, _get_team_players_for_match
from matches.melee_roster_resolution import (
    players_for_match_team,
    resolve_player_match_side,
)
from matches.models import Match, MatchActivation, MatchPlayer
from pfc_core.session_refresh import refresh_player_team_session
from pfc_core.smart_router import _resolve_tournament_matches
from teams.models import Player, Team
from tournaments.models import (
    MeleePlayer,
    MeleeRoundAssignment,
    Round,
    Stage,
    Tournament,
    TournamentTeam,
)


class MeleeRoundAssignmentConsumerTests(TestCase):
    """P3 readers use Match snapshot, then exact Mêlée Round, then fallback."""

    def setUp(self):
        now = timezone.now()
        self.tournament = Tournament.objects.create(
            name='P3 Mêlée Consumer Tournament',
            format='multi_stage',
            play_format='doublets',
            is_melee=True,
            melee_format='doublets',
            shuffle_players_after_round=True,
            start_date=now,
            end_date=now + timedelta(days=1),
        )
        self.stage = Stage.objects.create(
            tournament=self.tournament,
            stage_number=1,
            format='swiss',
            num_qualifiers=1,
            num_rounds_in_stage=3,
        )
        self.round_one = Round.objects.create(
            tournament=self.tournament,
            stage=self.stage,
            number=1,
            number_in_stage=1,
        )
        self.round_two = Round.objects.create(
            tournament=self.tournament,
            stage=self.stage,
            number=2,
            number_in_stage=2,
        )

        self.home_teams = [
            Team.objects.create(name=f'P3 Home Team {index}') for index in range(1, 5)
        ]
        self.round_one_team_a = Team.objects.create(
            name='P3 Round 1 Team A', is_tournament_temp=True
        )
        self.round_one_team_b = Team.objects.create(
            name='P3 Round 1 Team B', is_tournament_temp=True
        )
        self.round_two_team_a = Team.objects.create(
            name='P3 Round 2 Team A', is_tournament_temp=True
        )
        self.round_two_team_b = Team.objects.create(
            name='P3 Round 2 Team B', is_tournament_temp=True
        )
        for team in (
            self.round_one_team_a,
            self.round_one_team_b,
            self.round_two_team_a,
            self.round_two_team_b,
        ):
            TournamentTeam.objects.create(tournament=self.tournament, team=team)

        self.players = []
        for index, home_team in enumerate(self.home_teams, start=1):
            player = Player.objects.create(name=f'P3 Player {index}', team=home_team)
            MeleePlayer.objects.create(
                tournament=self.tournament,
                player=player,
                original_team=home_team,
            )
            PlayerCodename.objects.create(player=player, codename=f'P30{index:03d}')
            self.players.append(player)
        self.player_a, self.player_b, self.player_c, self.player_d = self.players

        self._assign(
            self.round_one,
            {
                self.player_a: self.round_one_team_a,
                self.player_b: self.round_one_team_a,
                self.player_c: self.round_one_team_b,
                self.player_d: self.round_one_team_b,
            },
        )
        self._assign(
            self.round_two,
            {
                self.player_a: self.round_two_team_a,
                self.player_b: self.round_two_team_b,
                self.player_c: self.round_two_team_a,
                self.player_d: self.round_two_team_b,
            },
        )

        # The legacy projection deliberately contradicts each exact Round. P3
        # must never use this value when MatchPlayer/MRA data exists.
        for player in self.players:
            player.team = self.home_teams[(player.id + 1) % len(self.home_teams)]
            player.save(update_fields=['team'])

        self.pending_round_one = self._match(
            self.round_one, self.round_one_team_a, self.round_one_team_b
        )
        self.historical_round_one = self._match(
            self.round_one,
            self.round_one_team_a,
            self.round_one_team_b,
            status='completed',
        )
        self.pending_round_two = self._match(
            self.round_two, self.round_two_team_a, self.round_two_team_b
        )
        self._snapshot(
            self.historical_round_one,
            self.round_one_team_a,
            (self.player_a, self.player_b),
        )
        self._snapshot(
            self.historical_round_one,
            self.round_one_team_b,
            (self.player_c, self.player_d),
        )

    def _assign(self, round_obj, assignments):
        for player, team in assignments.items():
            MeleeRoundAssignment.objects.create(
                tournament=self.tournament,
                round=round_obj,
                player=player,
                team=team,
                state=MeleeRoundAssignment.ASSIGNED,
            )

    def _match(self, round_obj, team_one, team_two, status='pending'):
        return Match.objects.create(
            tournament=self.tournament,
            stage=self.stage,
            round=round_obj,
            team1=team_one,
            team2=team_two,
            status=status,
        )

    @staticmethod
    def _snapshot(match, team, players):
        for player in players:
            MatchPlayer.objects.create(match=match, player=player, team=team)

    def _session_for(self, player):
        codename = PlayerCodename.objects.get(player=player).codename
        session = self.client.session
        session['player_codename'] = codename
        session.save()

    def test_pending_round_one_roster_uses_exact_round_assignments(self):
        """Pending Mêlée activation ignores deliberately conflicting Player.team."""
        team_a_players = list(
            _get_team_players_for_match(
                self.pending_round_one, self.round_one_team_a
            ).values_list('id', flat=True)
        )
        team_b_players = list(
            _get_team_players_for_match(
                self.pending_round_one, self.round_one_team_b
            ).values_list('id', flat=True)
        )

        self.assertEqual(team_a_players, [self.player_a.id, self.player_b.id])
        self.assertEqual(team_b_players, [self.player_c.id, self.player_d.id])
        self.assertEqual(
            resolve_player_match_side(self.pending_round_one, self.player_a),
            self.round_one_team_a,
        )

    def test_matchplayer_snapshot_is_authoritative_after_later_reshuffle(self):
        """A historic Round 1 Match stays on its original side after Round 2."""
        self.player_a.team = self.round_two_team_b
        self.player_a.save(update_fields=['team'])

        self.assertEqual(
            resolve_player_match_side(self.historical_round_one, self.player_a),
            self.round_one_team_a,
        )
        self.assertEqual(
            list(
                players_for_match_team(
                    self.historical_round_one, self.round_one_team_a
                ).values_list('id', flat=True)
            ),
            [self.player_a.id, self.player_b.id],
        )

    def test_pending_round_two_and_activation_form_use_round_two_assignments(self):
        """Round 2 pending roster is independent from Player.team and Round 1."""
        self.player_a.team = self.round_one_team_b
        self.player_a.save(update_fields=['team'])

        form = MatchActivationForm(self.pending_round_two, self.round_two_team_a)
        self.assertEqual(
            list(form.fields['players'].queryset.values_list('id', flat=True)),
            [self.player_a.id, self.player_c.id],
        )
        self.assertEqual(
            resolve_player_match_side(self.pending_round_two, self.player_a),
            self.round_two_team_a,
        )

    def test_explicit_nonplaying_assignment_never_falls_back_to_player_team(self):
        """A waitlisted/bey state cannot be revived through legacy affiliation."""
        MeleeRoundAssignment.objects.filter(
            tournament=self.tournament,
            round=self.round_two,
            player=self.player_a,
        ).delete()
        MeleeRoundAssignment.objects.create(
            tournament=self.tournament,
            round=self.round_two,
            player=self.player_a,
            team=None,
            state=MeleeRoundAssignment.WAITLISTED,
        )
        self.player_a.team = self.round_two_team_a
        self.player_a.save(update_fields=['team'])

        self.assertIsNone(
            resolve_player_match_side(self.pending_round_two, self.player_a)
        )
        self.assertEqual(
            list(
                players_for_match_team(
                    self.pending_round_two, self.round_two_team_a
                ).values_list('id', flat=True)
            ),
            [self.player_c.id],
        )

    def test_match_detail_resolves_pending_melee_side_from_exact_round(self):
        """Detail-page opponent/team context does not require temporary Player.team."""
        self._session_for(self.player_a)

        response = self.client.get(
            reverse('match_detail', kwargs={'match_id': self.pending_round_two.id})
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['my_team'], self.round_two_team_a)
        self.assertEqual(response.context['opponent_team'], self.round_two_team_b)

    def test_tournament_overview_uses_exact_assignment_for_unactivated_side(self):
        """The overview renders Round 2 teams without Player.team membership."""
        self.pending_round_two.status = 'pending_verification'
        self.pending_round_two.save(update_fields=['status'])

        response = self.client.get(
            reverse(
                'tournament_overview',
                kwargs={'tournament_id': self.tournament.id},
            )
        )

        self.assertEqual(response.status_code, 200)
        item = next(
            entry
            for entry in response.context['tournament_scoreboards']
            if entry['match'].id == self.pending_round_two.id
        )
        self.assertEqual(
            list(item['team1_players'].values_list('id', flat=True)),
            [self.player_a.id, self.player_c.id],
        )
        self.assertEqual(
            list(item['team2_players'].values_list('id', flat=True)),
            [self.player_b.id, self.player_d.id],
        )

    def test_smart_button_finds_exact_round_two_match_despite_team_drift(self):
        """Smart routing derives the pending action from exact Round 2 MRA."""
        self.pending_round_one.status = 'completed'
        self.pending_round_one.save(update_fields=['status'])
        self._session_for(self.player_a)

        response = self.client.post(reverse('pfc_next_url'))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            payload['next_url'],
            reverse(
                'match_activate',
                kwargs={
                    'match_id': self.pending_round_two.id,
                    'team_id': self.round_two_team_a.id,
                },
            ),
        )

    def test_smart_button_deduplicates_one_match_with_snapshots_and_assignments(self):
        """One actionable Mêlée Match must not become repeated router choices."""
        self.pending_round_one.status = 'completed'
        self.pending_round_one.save(update_fields=['status'])
        self._snapshot(
            self.pending_round_two,
            self.round_two_team_a,
            (self.player_a, self.player_c),
        )
        self._snapshot(
            self.pending_round_two,
            self.round_two_team_b,
            (self.player_b, self.player_d),
        )

        candidates = _resolve_tournament_matches(self.player_a)

        self.assertEqual(len(candidates), 1)
        expected_url = reverse(
            'match_activate',
            kwargs={
                'match_id': self.pending_round_two.id,
                'team_id': self.round_two_team_a.id,
            },
        )
        self.assertEqual(candidates[0]['url'], expected_url)

        self._session_for(self.player_a)
        response = self.client.get(reverse('my_active_matches'))
        self.assertRedirects(response, expected_url, fetch_redirect_response=False)

    def test_smart_button_retains_two_genuinely_distinct_actionable_matches(self):
        """SQL Match de-duplication does not merge separate Match actions."""
        candidates = _resolve_tournament_matches(self.player_a)

        expected_urls = {
            reverse(
                'match_activate',
                kwargs={
                    'match_id': self.pending_round_one.id,
                    'team_id': self.round_one_team_a.id,
                },
            ),
            reverse(
                'match_activate',
                kwargs={
                    'match_id': self.pending_round_two.id,
                    'team_id': self.round_two_team_a.id,
                },
            ),
        }
        self.assertEqual({candidate['url'] for candidate in candidates}, expected_urls)

        self._session_for(self.player_a)
        response = self.client.get(reverse('my_active_matches'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_count'], 2)

    def test_qr_pending_opponent_uses_round_assignment_not_player_team(self):
        """QR activation accepts an assigned opponent whose Player.team conflicts."""
        qr_match = self._match(
            self.round_two, self.round_two_team_a, self.round_two_team_b
        )
        self._snapshot(qr_match, self.round_two_team_a, (self.player_a, self.player_c))
        MatchActivation.objects.create(
            match=qr_match,
            team=self.round_two_team_a,
            pin_used=self.round_two_team_a.pin,
            is_initiator=True,
        )
        qr_match.status = 'pending_verification'
        qr_match.save(update_fields=['status'])

        self._session_for(self.player_a)
        session = self.client.session
        session['qr_resolved_codename'] = PlayerCodename.objects.get(
            player=self.player_b
        ).codename
        session.save()

        response = self.client.post(
            reverse('match_qr_confirm_opponent', kwargs={'match_id': qr_match.id})
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            MatchActivation.objects.filter(
                match=qr_match, team=self.round_two_team_b
            ).exists()
        )
        self.assertEqual(
            set(
                MatchPlayer.objects.filter(
                    match=qr_match, team=self.round_two_team_b
                ).values_list('player_id', flat=True)
            ),
            {self.player_b.id, self.player_d.id},
        )

    def test_initial_qr_activation_uses_exact_assignment_for_scanned_opponent(self):
        """Initial QR activation does not require scanned Player.team to match."""
        self._session_for(self.player_a)
        session = self.client.session
        session['qr_resolved_codename'] = PlayerCodename.objects.get(
            player=self.player_c
        ).codename
        session.save()

        response = self.client.post(
            reverse(
                'match_activate',
                kwargs={
                    'match_id': self.pending_round_one.id,
                    'team_id': self.round_one_team_a.id,
                },
            ),
            {
                'pin': self.round_one_team_a.pin,
                'players': [self.player_a.id, self.player_b.id],
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            MatchActivation.objects.filter(
                match=self.pending_round_one, team=self.round_one_team_a
            ).exists()
        )
        self.assertTrue(
            MatchActivation.objects.filter(
                match=self.pending_round_one, team=self.round_one_team_b
            ).exists()
        )
        self.assertEqual(
            set(
                MatchPlayer.objects.filter(
                    match=self.pending_round_one, team=self.round_one_team_b
                ).values_list('player_id', flat=True)
            ),
            {self.player_c.id, self.player_d.id},
        )

    def test_activation_notification_uses_exact_pending_opponent_roster(self):
        """First-activation Push target comes from Round assignment, not Team.players."""
        self._session_for(self.player_a)
        with patch(
            'pfc_events.push_notifications.notify_match_action_required'
        ) as notification_mock:
            response = self.client.post(
                reverse(
                    'match_activate',
                    kwargs={
                        'match_id': self.pending_round_one.id,
                        'team_id': self.round_one_team_a.id,
                    },
                ),
                {
                    'pin': self.round_one_team_a.pin,
                    'players': [self.player_a.id, self.player_b.id],
                },
            )

        self.assertEqual(response.status_code, 302)
        recipients, action, object_type, object_id = notification_mock.call_args.args
        self.assertEqual(action, 'opponent_started')
        self.assertEqual(object_type, 'match')
        self.assertEqual(object_id, self.pending_round_one.id)
        self.assertEqual(
            {player.id for player in recipients},
            {self.player_c.id, self.player_d.id},
        )

    def test_new_match_notification_uses_exact_round_assignment_rosters(self):
        """The post-commit new-Match Push uses P3 exact assignment recipients."""
        with patch(
            'pfc_events.push_notifications.notify_match_action_required'
        ) as notification_mock, patch('pfc_events.signals.notify_match_state_changed'):
            with self.captureOnCommitCallbacks(execute=True):
                match = self._match(
                    self.round_two, self.round_two_team_a, self.round_two_team_b
                )

        recipients, action, object_type, object_id = notification_mock.call_args.args
        self.assertEqual(action, 'new_match')
        self.assertEqual(object_type, 'match')
        self.assertEqual(object_id, match.id)
        self.assertEqual(
            {player.id for player in recipients},
            {self.player_a.id, self.player_b.id, self.player_c.id, self.player_d.id},
        )

    def test_result_validation_notification_uses_matchplayer_snapshot(self):
        """Post-activation notifications use MatchPlayer despite later Team drift."""
        active_match = self._match(
            self.round_one,
            self.round_one_team_a,
            self.round_one_team_b,
            status='active',
        )
        self._snapshot(active_match, self.round_one_team_a, (self.player_a, self.player_b))
        self._snapshot(active_match, self.round_one_team_b, (self.player_c, self.player_d))
        self.player_c.team = self.home_teams[0]
        self.player_c.save(update_fields=['team'])
        self._session_for(self.player_a)

        with patch(
            'pfc_events.push_notifications.notify_match_action_required'
        ) as notification_mock:
            response = self.client.post(
                reverse(
                    'match_submit_result',
                    kwargs={'match_id': active_match.id, 'team_id': self.round_one_team_a.id},
                ),
                {'team1_score': 13, 'team2_score': 7},
            )

        self.assertEqual(response.status_code, 302)
        recipients, action, object_type, object_id = notification_mock.call_args.args
        self.assertEqual(action, 'result_validation')
        self.assertEqual(object_type, 'match')
        self.assertEqual(object_id, active_match.id)
        self.assertEqual(
            {player.id for player in recipients},
            {self.player_c.id, self.player_d.id},
        )

    def test_session_refresh_sets_melee_context_without_replacing_normal_team_keys(self):
        """P4 preserves normal Team session identity while enabling fast polling."""
        session = self.client.session
        session['player_id'] = self.player_a.id
        session['team_id'] = self.home_teams[0].id
        session['team_name'] = self.home_teams[0].name
        session['team_pin'] = self.home_teams[0].pin
        session.save()
        self.player_a.team = self.home_teams[0]
        self.player_a.save(update_fields=['team'])

        updated = refresh_player_team_session(
            self.player_a,
            assignment_team=self.round_two_team_a,
            in_melee_assignment=True,
        )

        self.assertEqual(updated, 1)
        session = self.client.session
        self.assertEqual(session['team_id'], self.home_teams[0].id)
        self.assertEqual(session['team_name'], self.home_teams[0].name)
        self.assertEqual(session['team_pin'], self.home_teams[0].pin)
        self.assertTrue(session['in_melee_assignment'])

    def test_non_melee_match_retains_legacy_team_membership_behavior(self):
        """P3 does not alter ordinary Team Tournament Player.team semantics."""
        normal_tournament = Tournament.objects.create(
            name='P3 Ordinary Team Tournament',
            format='round_robin',
            play_format='doublets',
            start_date=timezone.now(),
            end_date=timezone.now() + timedelta(days=1),
        )
        team_one = Team.objects.create(name='P3 Normal Team One')
        team_two = Team.objects.create(name='P3 Normal Team Two')
        normal_player = Player.objects.create(name='P3 Normal Player', team=team_one)
        normal_match = Match.objects.create(
            tournament=normal_tournament,
            team1=team_one,
            team2=team_two,
        )

        self.assertEqual(resolve_player_match_side(normal_match, normal_player), team_one)
        self.assertEqual(
            list(
                players_for_match_team(normal_match, team_one).values_list('id', flat=True)
            ),
            [normal_player.id],
        )
