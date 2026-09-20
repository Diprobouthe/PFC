from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.template.loader import get_template
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from matches.models import LiveScoreboard, Match, MatchPlayer, ScoreUpdate
from matches.starting_team import (
    announce_match_starting_team,
    ensure_match_starting_team,
    match_has_first_real_score,
)
from teams.models import Player, Team
from tournaments.models import Tournament


class TournamentStartingTeamTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.tournament = Tournament.objects.create(
            name="Starting Team Test",
            play_format="doublets",
            start_date=now,
            end_date=now + timedelta(hours=2),
        )
        self.team1 = Team.objects.create(name="North", pin="140001")
        self.team2 = Team.objects.create(name="South", pin="140002")
        self.player1 = Player.objects.create(name="North Player", team=self.team1)
        self.player2 = Player.objects.create(name="South Player", team=self.team2)
        self.match = Match.objects.create(
            tournament=self.tournament,
            team1=self.team1,
            team2=self.team2,
            status="active",
        )
        MatchPlayer.objects.create(match=self.match, player=self.player1, team=self.team1)
        MatchPlayer.objects.create(match=self.match, player=self.player2, team=self.team2)

    def test_draw_is_persisted_once_and_never_replaced(self):
        with patch("matches.starting_team.choice", return_value=self.team1.id):
            selected, newly_selected = ensure_match_starting_team(self.match)
        self.assertTrue(newly_selected)
        self.assertEqual(selected, self.team1)

        self.match.refresh_from_db()
        self.assertEqual(self.match.starting_team, self.team1)
        with patch("matches.starting_team.choice", return_value=self.team2.id):
            selected, newly_selected = ensure_match_starting_team(self.match)
        self.assertFalse(newly_selected)
        self.assertEqual(selected, self.team1)
        self.match.refresh_from_db()
        self.assertEqual(self.match.starting_team, self.team1)

    @patch("pfc_events.push_notifications.notify_match_action_required")
    def test_only_the_persisted_selected_side_receives_existing_push_pattern(self, notify):
        with patch("matches.starting_team.choice", return_value=self.team2.id):
            selected = announce_match_starting_team(self.match)
        self.assertEqual(selected, self.team2)
        notify.assert_called_once()
        recipients, event_kind, object_type, object_id = notify.call_args.args
        self.assertEqual([player.id for player in recipients], [self.player2.id])
        self.assertEqual((event_kind, object_type, object_id), ("match_starts", "match", self.match.id))

        announce_match_starting_team(self.match)
        self.assertEqual(notify.call_count, 1)

    def test_first_non_zero_score_ends_the_persisted_draw_announcement(self):
        scoreboard, _created = LiveScoreboard.objects.get_or_create(
            tournament_match=self.match,
        )
        self.assertFalse(match_has_first_real_score(self.match))
        ScoreUpdate.objects.create(
            scoreboard=scoreboard,
            team1_score=0,
            team2_score=0,
            scorekeeper_codename="TEST",
            update_type="reset",
        )
        self.assertFalse(match_has_first_real_score(self.match))
        ScoreUpdate.objects.create(
            scoreboard=scoreboard,
            team1_score=1,
            team2_score=0,
            scorekeeper_codename="TEST",
            update_type="increment",
        )
        self.assertTrue(match_has_first_real_score(self.match))

    def test_partial_keeps_visibility_selected_side_only_until_first_score(self):
        template = get_template("partials/tournament_starting_team_announcement.html")
        match = SimpleNamespace(starting_team=SimpleNamespace(name="North"))
        visible = template.render(
            {
                "match": match,
                "starting_team_is_recipient": True,
                "starting_team_has_score": False,
                "starting_team_scoreboard_id": 23,
                "listen_for_score_updates": False,
            }
        )
        self.assertIn("North", visible)
        self.assertIn("starts first", visible)

        hidden_for_opponent = template.render(
            {
                "match": match,
                "starting_team_is_recipient": False,
                "starting_team_has_score": False,
                "listen_for_score_updates": False,
            }
        )
        self.assertNotIn('id="tournament-starting-team-banner"', hidden_for_opponent)

        hidden_after_score = template.render(
            {
                "match": match,
                "starting_team_is_recipient": True,
                "starting_team_has_score": True,
                "listen_for_score_updates": False,
            }
        )
        self.assertNotIn('id="tournament-starting-team-banner"', hidden_after_score)

    def test_pre_start_and_score_entry_show_match_specific_side_players(self):
        self.match.status = "pending"
        self.match.save(update_fields=["status", "updated_at"])
        pre_start = self.client.get(reverse("match_detail", args=[self.match.id]))
        self.assertEqual(pre_start.status_code, 200)
        self.assertContains(pre_start, self.player1.name)
        self.assertContains(pre_start, self.player2.name)

        self.match.status = "active"
        self.match.save(update_fields=["status", "updated_at"])
        score_entry = self.client.get(
            reverse("match_submit_result", args=[self.match.id, self.team1.id]),
        )
        self.assertEqual(score_entry.status_code, 200)
        self.assertContains(score_entry, self.player1.name)
        self.assertContains(score_entry, self.player2.name)

        shared_score_entry = self.client.get(
            reverse("scoreboard_detail", args=[self.match.live_scoreboard.id]),
        )
        self.assertEqual(shared_score_entry.status_code, 200)
        self.assertContains(
            shared_score_entry,
            'class="score-entry-player-names"',
            count=2,
        )
        self.assertContains(shared_score_entry, self.player1.name)
        self.assertContains(shared_score_entry, self.player2.name)
