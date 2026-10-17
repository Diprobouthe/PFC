"""Read-only PDF export regressions, including missing and split historical data."""
import os
from pathlib import Path
from io import BytesIO

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from friendly_games.models import PlayerCodename
from matches.models import Match, MatchPlayer, LiveScoreboard
from practice.models import PracticeSession
from teams.models import Team, Player
from tournaments.models import Tournament
from match_tracking.models import MatchTrackingSession, TrackingPracticeSession
from match_tracking.views import _get_player_shot_stats


class HistoricalMatchPDFTests(TestCase):
    def setUp(self):
        self.a = Team.objects.create(name="Αθήνα Α", pin="763100")
        self.b = Team.objects.create(name="Αθήνα Β", pin="763101")
        self.alice = Player.objects.create(name="Μαρία Δοκιμή", team=self.a)
        self.bob = Player.objects.create(name="Γιάννης Δοκιμή", team=self.b)
        self.tournament = Tournament.objects.create(
            name="PDF ιστορικός", play_format="doublets",
            start_date=timezone.now(), end_date=timezone.now(),
        )
        self.match = Match.objects.create(
            tournament=self.tournament, team1=self.a, team2=self.b,
            status="completed", team1_score=13, team2_score=7,
            winner=self.a, loser=self.b,
        )
        MatchPlayer.objects.create(match=self.match, team=self.a, player=self.alice)
        MatchPlayer.objects.create(match=self.match, team=self.b, player=self.bob)
        self.scoreboard = LiveScoreboard.objects.get_or_create(
            tournament_match=self.match
        )[0]
        self.scoreboard.team1_score = 0
        self.scoreboard.team2_score = 0
        self.scoreboard.save(update_fields=["team1_score", "team2_score"])

    def add_recording(self, player, total, hits, kind="shooting"):
        tracking = MatchTrackingSession.objects.create(
            match_type="match", match_pk=self.match.pk, status="ended"
        )
        session = PracticeSession.objects.create(
            player_codename="PDF001" if player == self.alice else "PDF002",
            practice_type=kind, is_active=False, total_shots=total,
            hits=hits if kind == "shooting" else 0,
            goods=hits if kind == "pointing" else 0,
        )
        TrackingPracticeSession.objects.create(
            tracking_session=tracking, player=player,
            practice_session=session, practice_type=kind,
        )

    def read_pdf(self):
        response = self.client.get(reverse(
            "match_tracking:export_pdf", args=["match", self.match.pk]
        ))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        return "\n".join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)

    def test_historical_periods_aggregate_by_player_without_crossing_other_players(self):
        self.add_recording(self.alice, 4, 2)
        self.add_recording(self.alice, 6, 4)
        self.add_recording(self.bob, 5, 1)
        self.add_recording(self.bob, 3, 2, kind="pointing")

        alice = _get_player_shot_stats(self.alice.pk, "match", self.match.pk)
        bob = _get_player_shot_stats(self.bob.pk, "match", self.match.pk)
        self.assertEqual(alice["shooting"]["total"], 10)
        self.assertEqual(alice["shooting"]["hits"], 6)
        self.assertEqual(alice["shooting"]["accuracy"], 60.0)
        self.assertEqual(bob["shooting"]["total"], 5)
        self.assertEqual(bob["pointing"]["total"], 3)
        text = self.read_pdf()
        self.assertIn("Μαρία Δοκιμή", text)
        self.assertIn("Γιάννης Δοκιμή", text)
        self.assertIn("10", text)
        self.assertIn("60.0%", text)
        self.assertIn("Επικυρωμένο αποτέλεσμα", text)
        self.assertIn("13 – 7", text)

    def test_no_recordings_never_fabricate_zeros_as_shots(self):
        text = self.read_pdf()
        self.assertIn("Δεν έχουν καταγραφεί βολές", text)
        self.assertIn("13 – 7", text)

    def test_match_data_isolation_even_if_other_match_has_same_player(self):
        other = Match.objects.create(
            tournament=self.tournament, team1=self.a, team2=self.b,
            status="completed",
        )
        tracking = MatchTrackingSession.objects.create(
            match_type="match", match_pk=other.pk, status="ended"
        )
        session = PracticeSession.objects.create(
            player_codename="PDF001", practice_type="shooting",
            total_shots=9, hits=9,
        )
        TrackingPracticeSession.objects.create(
            tracking_session=tracking, player=self.alice,
            practice_session=session, practice_type="shooting",
        )
        self.assertEqual(
            _get_player_shot_stats(self.alice.pk, "match", self.match.pk)["shooting"]["total"],
            0,
        )
