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
        # Realistic compact-sheet fixtures with distinct published lineups for
        # all three formats. The pending fourth match is intentionally not
        # assigned to a format or exposed before the opposing captain locks.
        self.more_a = [
            Player.objects.create(name="Ελένη", team=self.a),
            Player.objects.create(name="Δήμητρα", team=self.a),
        ]
        self.more_b = [
            Player.objects.create(name="Αλέξης", team=self.b),
            Player.objects.create(name="Σοφία", team=self.b),
        ]
        self.doublet = self.finished_game(
            "doublet", 3, [self.player_a, self.more_a[0]],
            [self.player_b, self.more_b[0]], 13, 9, self.a,
        )
        self.triplet = self.finished_game(
            "triplet", 5, [self.player_a, *self.more_a],
            [self.player_b, *self.more_b], 8, 13, self.b,
        )
        self.pdf_url = reverse("tournament_report_pdf", args=[self.tournament.pk])

    def finished_game(self, fmt, vs_points, players_a, players_b, score_a, score_b, winner):
        game = Match.objects.create(
            tournament=self.tournament, vs_encounter=self.encounter,
            team1=self.a, team2=self.b, status="completed",
            match_type=fmt, vs_points_value=vs_points,
            winner=winner, loser=self.b if winner == self.a else self.a,
            team1_score=score_a, team2_score=score_b,
            vs_lineup_team1_locked=True, vs_lineup_team2_locked=True,
        )
        for team, players in ((self.a, players_a), (self.b, players_b)):
            lineup = VSLineup.objects.create(match=game, team=team, is_locked=True)
            lineup.players.add(*players)
        return game

    def finish_pending(self):
        self.pending.status = "completed"
        self.pending.match_type = "doublet"
        self.pending.vs_points_value = 3
        self.pending.team1_score = 4
        self.pending.team2_score = 13
        self.pending.winner = self.b
        self.pending.loser = self.a
        self.pending.vs_lineup_team2_locked = True
        self.pending.save()
        team1_lineup = self.pending.vs_lineups.get(team=self.a)
        team1_lineup.players.add(self.more_a[0])
        other = VSLineup.objects.create(
            match=self.pending, team=self.b, is_locked=True,
        )
        other.players.add(self.player_b, self.more_b[0])

    def pdf_text(self):
        response = self.client.get(self.pdf_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        sample_dir = os.getenv("PFC_PDF_SAMPLE_DIR")
        if sample_dir:
            Path(sample_dir).mkdir(parents=True, exist_ok=True)
            (Path(sample_dir) / "vs_tournament_final_demo.pdf").write_bytes(response.content)
        return "\n".join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)

    def test_before_all_results_validated_pdf_is_unavailable_even_via_direct_url(self):
        from tournaments.pdf_reports import _match_row
        self.assertEqual(_match_row(self.pending)[1], "Σύνθεση σε αναμονή")
        self.assertEqual(_match_row(self.pending)[3], "Σύνθεση σε αναμονή")
        response = self.client.get(self.pdf_url)
        self.assertEqual(response.status_code, 409)
        self.assertNotEqual(response["Content-Type"], "application/pdf")
        self.assertIn("επικύρωση", response.content.decode())
        page = self.client.get(reverse("tournament_detail", args=[self.tournament.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertFalse(page.context["vs_report_ready"])
        self.assertNotContains(page, 'onclick="sharePFCTournamentReport')

    def test_final_pdf_is_read_only_and_renders_real_lineups(self):
        self.finish_pending()
        original_updated_at = self.tournament.updated_at
        result = self.pdf_text()
        self.assertIn("VS ΠΕΤΑ Δοκιμή", result)
        self.assertIn("ΤΕΛΙΚΟ", result)
        self.assertNotIn("ΠΡΟΣΩΡΙΝΟ", result)
        self.assertIn("13 – 8", result)
        self.assertIn("Αθηνά", result)
        self.assertIn("2", result)
        self.tournament.refresh_from_db()
        self.assertEqual(self.tournament.updated_at, original_updated_at)
        page = self.client.get(reverse("tournament_detail", args=[self.tournament.pk]))
        self.assertTrue(page.context["vs_report_ready"])
        self.assertContains(page, 'onclick="sharePFCTournamentReport')

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
        self.finish_pending()
        self.assertIn("Επίσημες παρατηρήσεις διοργάνωσης", self.pdf_text())
        too_long = self.client.post(url, {"report_notes": "X" * 2001})
        self.assertEqual(too_long.status_code, 400)

    def test_pdf_opens_at_final_result_without_manually_closing_tournament(self):
        self.assertEqual(self.client.get(self.pdf_url).status_code, 409)
        self.finish_pending()
        self.assertTrue(self.tournament.is_active)
        rendered = self.pdf_text()
        self.assertIn("ΤΕΛΙΚΟ", rendered)
        self.assertIn("4 – 13", rendered)
        self.assertIn("13 – 8", rendered)
        self.assertIn("Πεδίο Άρεως", rendered)

    def test_waiting_for_validation_is_not_final(self):
        Match.objects.filter(pk=self.pending.pk).update(
            match_type="doublet", status="waiting_validation",
            team1_score=13, team2_score=10,
        )
        self.assertEqual(self.client.get(self.pdf_url).status_code, 409)

    def test_compact_sheet_groups_formats_and_prints_real_player_lineups(self):
        self.finish_pending()
        rendered = self.pdf_text()
        singles = rendered.find("ΜΟΝΑ")
        doubles = rendered.find("ΔΙΠΛΑ")
        triples = rendered.find("ΤΡΙΠΛΑ")
        self.assertTrue(0 <= singles < doubles < triples, rendered)
        self.assertNotIn("ΕΚΚΡΕΜΗ", rendered)
        self.assertNotIn("ΧΩΡΙΣ ΟΡΙΣΜΕΝΗ ΜΟΡΦΗ", rendered)
        for player in ("Αθηνά", "Πέτρος", "Ελένη", "Αλέξης", "Δήμητρα", "Σοφία"):
            self.assertIn(player, rendered)
        self.assertIn("πετΑ UMP", rendered)
        self.assertNotIn("πέτα UMP", rendered)
        # No fabricated player substitution: the database has none.
        self.assertNotIn("Αντικατάσταση", rendered)

    def test_typical_three_games_fit_on_one_a4_page(self):
        self.pending.delete()
        response = self.client.get(self.pdf_url)
        self.assertEqual(response.status_code, 200)
        pages = PdfReader(BytesIO(response.content)).pages
        self.assertEqual(len(pages), 1)

    def test_no_encounter_or_no_games_cannot_generate_blank_sheet(self):
        self.pending.delete()
        self.first.delete()
        self.doublet.delete()
        self.triplet.delete()
        self.assertEqual(self.client.get(self.pdf_url).status_code, 409)
        self.encounter.delete()
        self.assertEqual(self.client.get(self.pdf_url).status_code, 409)

    def test_non_vs_report_is_not_generated(self):
        self.tournament.allowed_match_types = {}
        self.tournament.save(update_fields=["allowed_match_types"])
        self.assertEqual(self.client.get(self.pdf_url).status_code, 404)
