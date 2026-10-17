"""PDF certification/report tests for entire VS tournaments."""
import os
from pathlib import Path
from io import BytesIO

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from matches.models import Match
from teams.models import Team, Player
from tournaments.models import Tournament, TournamentTeam, VSEncounter, VSLineup


class VSTournamentReportPDFTests(TestCase):
    def setUp(self):
        self.tournament = Tournament.objects.create(
            name="VS ΠΕΤΑ Δοκιμή", format="independent_games",
            play_format="mixed", is_active=True,
            allowed_match_types={"vs_mode": True},
            start_date=timezone.now(), end_date=timezone.now(),
        )
        self.a = Team.objects.create(name="Αθηναϊκοί", pin="793101")
        self.b = Team.objects.create(name="Πεδίο Άρεως", pin="793102")
        for team in (self.a, self.b):
            TournamentTeam.objects.create(tournament=self.tournament, team=team)
        self.player_a = Player.objects.create(name="Αθηνά", team=self.a)
        self.player_b = Player.objects.create(name="Πέτρος", team=self.b)
        self.encounter = VSEncounter.objects.create(
            tournament=self.tournament, team1=self.a, team2=self.b
        )
        self.first = Match.objects.create(
            tournament=self.tournament, vs_encounter=self.encounter,
            team1=self.a, team2=self.b, status="completed",
            match_type="tete_a_tete", vs_points_value=2,
            winner=self.a, loser=self.b, team1_score=13, team2_score=8,
            vs_lineup_team1_locked=True, vs_lineup_team2_locked=True,
        )
        for player, team in ((self.player_a, self.a), (self.player_b, self.b)):
            lineup = VSLineup.objects.create(match=self.first, team=team, is_locked=True)
            lineup.players.add(player)
        self.pending = Match.objects.create(
            tournament=self.tournament, vs_encounter=self.encounter,
            team1=self.a, team2=self.b, status="pending",
            vs_lineup_team1_locked=True, vs_lineup_team2_locked=False,
        )
        lineup = VSLineup.objects.create(match=self.pending, team=self.a, is_locked=True)
        lineup.players.add(self.player_a)
        self.pdf_url = reverse("tournament_report_pdf", args=[self.tournament.pk])

    def pdf_text(self):
        response = self.client.get(self.pdf_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        return "\n".join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)

    def test_tournament_pdf_is_read_only_and_discloses_only_locked_lineups(self):
        original_updated_at = self.tournament.updated_at
        original_count = Tournament.objects.count()
        result = self.pdf_text()
        self.assertIn("VS ΠΕΤΑ Δοκιμή", result)
        self.assertIn("ΠΡΟΣΩΡΙΝΟ", result)
        self.assertIn("13 – 8", result)
        self.assertIn("Αθηνά", result)  # Finished lineup may be displayed
        self.assertIn("2", result)      # Awarded VS points
        self.assertEqual(Tournament.objects.count(), original_count)
        self.tournament.refresh_from_db()
        self.assertEqual(self.tournament.updated_at, original_updated_at)

        # The waiting match must not disclose one-sided lineup before second lock.
        from tournaments.pdf_reports import _match_row
        self.assertNotIn("Αθηνά", _match_row(self.pending)[2])

    def test_staff_notes_are_saved_and_anonymous_may_not_change_them(self):
        url = reverse("update_tournament_report_notes", args=[self.tournament.pk])
        bad = self.client.post(url, {"report_notes": "Μη εξουσιοδοτημένη σημείωση"})
        self.assertEqual(bad.status_code, 302)
        self.tournament.refresh_from_db()
        self.assertEqual(self.tournament.report_notes, "")

        staff = get_user_model().objects.create_user(
            username="vs_report_editor", password="secure-test-password", is_staff=True
        )
        self.client.force_login(staff)
        posted = self.client.post(url, {"report_notes": "Επίσημες παρατηρήσεις διοργάνωσης"})
        self.assertEqual(posted.status_code, 302)
        self.tournament.refresh_from_db()
        self.assertEqual(self.tournament.report_notes, "Επίσημες παρατηρήσεις διοργάνωσης")
        self.assertIn("Επίσημες παρατηρήσεις διοργάνωσης", self.pdf_text())
        too_long = self.client.post(url, {"report_notes": "X" * 2001})
        self.assertEqual(too_long.status_code, 400)

    def test_final_only_after_tournament_is_closed_and_all_games_validated(self):
        self.assertIn("ΠΡΟΣΩΡΙΝΟ", self.pdf_text())
        Match.objects.filter(pk=self.pending.pk).update(
            status="completed", team1_score=4, team2_score=13,
            winner=self.b, loser=self.a, match_type="doublet",
            vs_points_value=3, vs_lineup_team2_locked=True,
        )
        VSLineup.objects.create(match=self.pending, team=self.b, is_locked=True).players.add(self.player_b)
        self.tournament.is_active = False
        self.tournament.save(update_fields=["is_active"])
        rendered = self.pdf_text()
        self.assertIn("ΤΕΛΙΚΟ", rendered)
        self.assertIn("4 – 13", rendered)
        self.assertIn("13 – 8", rendered)
        self.assertIn("Πεδίο Άρεως", rendered)

    def test_non_vs_report_is_not_generated(self):
        self.tournament.allowed_match_types = {}
        self.tournament.save(update_fields=["allowed_match_types"])
        self.assertEqual(self.client.get(self.pdf_url).status_code, 404)
