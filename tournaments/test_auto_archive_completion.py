from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from matches.models import Match
from teams.models import Team
from tournaments.automation_engine import TournamentEngine
from tournaments.completion import check_and_complete_tournament
from tournaments.models import Round, Stage, Tournament, TournamentTeam


class TournamentAutoArchiveCompletionTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.tournament = Tournament.objects.create(
            name="Auto Archive Completion Test",
            format="multi_stage",
            play_format="doublets",
            start_date=now,
            end_date=now + timedelta(hours=2),
            automation_status="idle",
            is_active=True,
            is_archived=False,
        )
        self.stage = Stage.objects.create(
            tournament=self.tournament,
            stage_number=1,
            name="Final Stage",
            format="swiss",
            num_qualifiers=1,
            num_rounds_in_stage=1,
            is_complete=False,
        )
        self.round = Round.objects.create(
            tournament=self.tournament,
            stage=self.stage,
            number=1,
            number_in_stage=1,
            is_complete=True,
        )
        self.team1 = Team.objects.create(name="Archive North")
        self.team2 = Team.objects.create(name="Archive South")
        TournamentTeam.objects.create(
            tournament=self.tournament,
            team=self.team1,
            current_stage_number=1,
            is_active=True,
        )
        TournamentTeam.objects.create(
            tournament=self.tournament,
            team=self.team2,
            current_stage_number=1,
            is_active=True,
        )
        Match.objects.create(
            tournament=self.tournament,
            round=self.round,
            stage=self.stage,
            team1=self.team1,
            team2=self.team2,
            status="completed",
            winner=self.team1,
            loser=self.team2,
            team1_score=13,
            team2_score=7,
        )

    @patch("tournaments.completion._assign_badges_if_needed", return_value=True)
    def test_engine_completion_archives_and_keeps_completed_status(self, _badges):
        result = TournamentEngine(self.tournament).process_automation()

        self.assertTrue(result)
        self.tournament.refresh_from_db()
        self.stage.refresh_from_db()

        self.assertEqual(self.tournament.automation_status, "completed")
        self.assertIsNone(self.tournament.current_round_number)
        self.assertFalse(self.tournament.is_active)
        self.assertTrue(self.tournament.is_archived)
        self.assertTrue(self.stage.is_complete)

    @patch("tournaments.completion._assign_badges_if_needed", return_value=True)
    def test_legacy_already_completed_path_is_reconciled_to_archive(self, _badges):
        self.tournament.automation_status = "completed"
        self.tournament.current_round_number = 1
        self.tournament.is_active = True
        self.tournament.is_archived = False
        self.tournament.save(
            update_fields=[
                "automation_status",
                "current_round_number",
                "is_active",
                "is_archived",
            ]
        )

        result = check_and_complete_tournament(self.tournament)

        self.assertTrue(result)
        self.tournament.refresh_from_db()
        self.stage.refresh_from_db()
        self.assertEqual(self.tournament.automation_status, "completed")
        self.assertIsNone(self.tournament.current_round_number)
        self.assertFalse(self.tournament.is_active)
        self.assertTrue(self.tournament.is_archived)
        self.assertTrue(self.stage.is_complete)
