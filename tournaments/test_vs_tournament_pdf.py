"""VS final-sheet QR approvals: membership, identity, finality and PDF freeze."""
import json
import os
from io import BytesIO
from datetime import datetime, timezone as datetime_timezone
from unittest.mock import patch
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from friendly_games.models import PlayerCodename
from courts.models import Court, CourtComplex
from matches.models import Match
from pfc_core.qr_utils import generate_player_token
from teams.models import Team, Player
from tournaments.models import (
    Tournament, TournamentTeam, VSEncounter, VSLineup, VSSheetAttestation,
)


class VSTournamentReportPDFTests(TestCase):
    def setUp(self):
        self.tournament = Tournament.objects.create(
            name="VS ΠΕΤΑ Δοκιμή", format="independent_games", play_format="mixed",
            is_active=True, allowed_match_types={"vs_mode": True},
            start_date=timezone.now(), end_date=timezone.now(),
        )
        self.a = Team.objects.create(name="Αθηναϊκοί", pin="793101")
        self.b = Team.objects.create(name="Πεδίο Άρεως", pin="793102")
        self.c = Team.objects.create(name="Τρίτη ομάδα", pin="793103")
        for team in (self.a, self.b):
            TournamentTeam.objects.create(tournament=self.tournament, team=team)
        self.player_a = self.player("Αθηνά", self.a, "ATA001")
        self.player_b = self.player("Πέτρος", self.b, "PET002")
        self.not_playing = self.player("Ανθή βοηθός", self.a, "ANT003")
        self.outsider = self.player("Γιώργος", self.c, "GIO004")
        self.extra_a = [self.player("Ελένη", self.a, "ELE005"), self.player("Δήμητρα", self.a, "DIM006")]
        self.extra_b = [self.player("Αλέξης", self.b, "ALE007"), self.player("Σοφία", self.b, "SOF008")]
        self.encounter = VSEncounter.objects.create(
            tournament=self.tournament, team1=self.a, team2=self.b,
        )
        self.first = self.game(
            "tete_a_tete", 2, [self.player_a], [self.player_b], 13, 8, self.a,
        )
        self.doublet = self.game(
            "doublet", 3, [self.player_a, self.extra_a[0]],
            [self.player_b, self.extra_b[0]], 13, 9, self.a,
        )
        self.triplet = self.game(
            "triplet", 5, [self.player_a, *self.extra_a],
            [self.player_b, *self.extra_b], 8, 13, self.b,
        )
        self.pending = Match.objects.create(
            tournament=self.tournament, vs_encounter=self.encounter,
            team1=self.a, team2=self.b, status="pending",
            vs_lineup_team1_locked=True, vs_lineup_team2_locked=False,
        )
        self.pdf_url = reverse("tournament_report_pdf", args=[self.tournament.pk])
        self.scan_url = reverse("vs_sheet_qr_resolve", args=[self.encounter.pk])
        self.attest_url = reverse("vs_sheet_attest", args=[self.encounter.pk])
        self.referee_url = reverse("vs_sheet_referee_setting", args=[self.encounter.pk])
        self.page_url = reverse("vs_encounter_detail", args=[self.encounter.pk])

    def player(self, name, team, codename):
        p = Player.objects.create(name=name, team=team)
        PlayerCodename.objects.create(player=p, codename=codename)
        return p

    def game(self, fmt, points, a, b, score_a, score_b, winner):
        match = Match.objects.create(
            tournament=self.tournament, vs_encounter=self.encounter,
            team1=self.a, team2=self.b, status="completed", match_type=fmt,
            vs_points_value=points, winner=winner,
            loser=self.b if winner == self.a else self.a,
            team1_score=score_a, team2_score=score_b,
            vs_lineup_team1_locked=True, vs_lineup_team2_locked=True,
        )
        for team, players in ((self.a, a), (self.b, b)):
            lineup = VSLineup.objects.create(match=match, team=team, is_locked=True)
            lineup.players.add(*players)
        return match

    def finish(self):
        self.pending.status = "completed"
        self.pending.match_type = "doublet"
        self.pending.vs_points_value = 3
        self.pending.team1_score = 4
        self.pending.team2_score = 13
        self.pending.winner = self.b
        self.pending.loser = self.a
        self.pending.vs_lineup_team2_locked = True
        self.pending.save()
        for team, players in ((self.a, [self.player_a, self.extra_a[0]]),
                              (self.b, [self.player_b, self.extra_b[0]])):
            lineup = VSLineup.objects.create(match=self.pending, team=team, is_locked=True)
            lineup.players.add(*players)

    def scan(self, player):
        return self.client.post(
            self.scan_url,
            data=json.dumps({"token": generate_player_token(player.id)}),
            content_type="application/json",
        )

    def accept(self, player, remarks=None):
        scan = self.scan(player)
        self.assertEqual(scan.status_code, 200, scan.content)
        self.assertTrue(scan.json()["ok"])
        if remarks is None:
            return self.client.post(self.attest_url)
        return self.client.post(
            self.attest_url,
            data=json.dumps({"remarks": remarks}),
            content_type="application/json",
        )

    def sign_both(self):
        self.assertTrue(self.accept(self.not_playing).json()["ok"])
        return self.accept(self.player_b)

    def pdf_text(self):
        response = self.client.get(self.pdf_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        folder = os.getenv("PFC_PDF_SAMPLE_DIR")
        if folder:
            Path(folder).mkdir(parents=True, exist_ok=True)
            (Path(folder) / "vs_tournament_final_demo.pdf").write_bytes(response.content)
        return "\n".join(page.extract_text() for page in PdfReader(BytesIO(response.content)).pages)

    def test_sheet_unavailable_before_all_games_or_without_team_attestations(self):
        self.assertEqual(self.client.get(self.pdf_url).status_code, 409)
        self.assertFalse(self.client.get(self.page_url).context["sheet"]["ready"])
        self.assertEqual(self.scan(self.player_a).status_code, 409)
        self.finish()
        self.assertTrue(self.client.get(self.page_url).context["sheet"]["ready"])
        self.assertEqual(self.client.get(self.pdf_url).status_code, 409)
        self.assertEqual(self.client.post(self.attest_url).status_code, 403)

    def test_two_team_members_finally_issue_immutable_pdf_without_closing_tournament(self):
        self.finish()
        result = self.sign_both()
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()["issued"])
        self.assertTrue(self.tournament.is_active)
        self.encounter.refresh_from_db()
        self.assertIsNotNone(self.encounter.sheet_issued_at)
        self.assertTrue(self.encounter.sheet_pdf)
        text = self.pdf_text()
        self.assertIn("Ανθή βοηθός", text)  # Team roster member who did not play.
        self.assertIn("Πέτρος", text)
        self.assertIn("Επικυρώθηκε μέσω PFC QR", text)
        self.assertIn("πετΑ UMP", text)
        self.assertNotIn("Υπογραφή:", text)
        self.assertNotIn("ΠΡΟΣΩΡΙΝΟ", text)
        self.assertTrue(self.client.get(self.page_url).context["sheet"]["locked"])
        self.assertEqual(self.scan(self.extra_a[0]).status_code, 409)
        frozen = bytes(self.encounter.sheet_pdf)
        self.assertEqual(self.client.get(self.pdf_url).content, frozen)

    def test_membership_is_current_team_roster_not_tournament_lineup_or_captain(self):
        self.finish()
        self.assertFalse(self.not_playing.is_captain)
        self.assertFalse(self.first.vs_lineups.filter(players=self.not_playing).exists())
        self.assertEqual(self.scan(self.not_playing).status_code, 200)
        result = self.client.post(self.attest_url)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json()["role"], "team1")
        self.assertEqual(VSSheetAttestation.objects.get(role="team1").player, self.not_playing)
        self.assertEqual(self.scan(self.outsider).status_code, 403)
        self.assertEqual(self.client.post(self.attest_url).status_code, 403)
        self.assertEqual(self.scan(self.extra_a[0]).status_code, 409)  # one signer per side
        self.assertEqual(self.scan(self.player_b).status_code, 200)

    def test_optional_qr_remarks_default_and_explicit_text_appear_in_frozen_pdf(self):
        self.finish()
        # An empty text field must be a real attestation with automatic status.
        first = self.accept(self.not_playing, remarks="")
        self.assertEqual(first.status_code, 200)
        self.assertFalse(first.json()["issued"])
        signed_a = VSSheetAttestation.objects.get(
            encounter=self.encounter, role="team1",
        )
        self.assertEqual(signed_a.remarks, "Όλα καλώς")

        # The other side attaches its own observations, not a shared note.
        note = "Στο διπλό σημειώθηκε διακοπή λόγω βροχής, χωρίς αλλαγή σκορ."
        second = self.accept(self.player_b, remarks=note)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json()["issued"])
        signed_b = VSSheetAttestation.objects.get(
            encounter=self.encounter, role="team2",
        )
        self.assertEqual(signed_b.remarks, note)
        self.assertEqual(signed_a.player_name, "Ανθή βοηθός")
        self.assertEqual(signed_b.player_name, "Πέτρος")
        text = self.pdf_text()
        self.assertIn("Παρατήρηση: Όλα καλώς", text)
        self.assertIn(note, text)
        self.assertIn("Ανθή βοηθός", text)
        self.assertIn("Πέτρος", text)
        view = self.client.get(self.page_url)
        self.assertContains(view, note)
        self.assertContains(view, "Όλα καλώς")
        pdf = self.client.get(self.pdf_url).content
        self.assertEqual(pdf, self.client.get(self.pdf_url).content)

    def test_invalid_qr_remarks_are_rejected_before_consuming_qr_proof(self):
        self.finish()
        self.assertEqual(self.scan(self.player_a).status_code, 200)
        too_long = self.client.post(
            self.attest_url,
            data=json.dumps({"remarks": "Λ" * 1001}),
            content_type="application/json",
        )
        self.assertEqual(too_long.status_code, 400)
        self.assertEqual(VSSheetAttestation.objects.count(), 0)
        # The same verified QR is still usable after fixing the input.
        accepted = self.client.post(
            self.attest_url,
            data=json.dumps({"remarks": "Συμφωνώ"}),
            content_type="application/json",
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(
            VSSheetAttestation.objects.get(encounter=self.encounter).remarks,
            "Συμφωνώ",
        )

    def test_referee_requires_organizer_opt_in_and_neutral_qr(self):
        self.finish()
        self.assertEqual(self.client.post(self.referee_url, {"enabled": "on"}).status_code, 302)
        self.encounter.refresh_from_db()
        self.assertFalse(self.encounter.sheet_referee_required)
        admin = get_user_model().objects.create_user(
            username="vs_admin", password="pass-12345", is_staff=True,
        )
        self.client.force_login(admin)
        self.assertEqual(self.client.post(self.referee_url, {"enabled": "on"}).status_code, 302)
        self.encounter.refresh_from_db()
        self.assertTrue(self.encounter.sheet_referee_required)
        self.assertEqual(self.client.get(self.pdf_url).status_code, 409)
        accepted = self.sign_both()
        self.assertFalse(accepted.json()["issued"])
        self.assertEqual(self.client.post(self.referee_url, {"enabled": ""}).status_code, 409)
        third = self.accept(self.outsider)
        self.assertTrue(third.json()["issued"])
        text = self.pdf_text()
        self.assertIn("Γιώργος", text)
        self.assertIn("χωρίς πιστοποίηση", text)

    def test_invalid_qr_and_forged_json_identity_cannot_attest(self):
        self.finish()
        fake = self.client.post(self.attest_url, data=json.dumps(
            {"player_id": self.player_a.pk, "role": "team1",
             "codename": "ATA001"}), content_type="application/json",
        )
        self.assertEqual(fake.status_code, 403)
        bad = self.client.post(self.scan_url, data=json.dumps({
            "token": generate_player_token(self.player_a.pk) + "FORGED"
        }), content_type="application/json")
        self.assertEqual(bad.status_code, 403)
        self.assertEqual(self.client.post(self.attest_url).status_code, 403)
        self.assertEqual(self.scan(self.player_a).status_code, 200)
        self.assertEqual(self.client.post(self.attest_url).status_code, 200)
        self.assertEqual(self.client.post(self.attest_url).status_code, 403)

    def test_notes_are_staff_only_and_frozen_after_first_attestation(self):
        notes_url = reverse("update_tournament_report_notes", args=[self.tournament.pk])
        self.assertEqual(self.client.post(notes_url, {"report_notes": "Changed"}).status_code, 302)
        self.tournament.refresh_from_db()
        self.assertEqual(self.tournament.report_notes, "")
        staff = get_user_model().objects.create_user(
            username="notes_staff", password="password-123", is_staff=True
        )
        self.client.force_login(staff)
        self.assertEqual(self.client.post(notes_url, {"report_notes": "Επίσημες σημειώσεις"}).status_code, 302)
        self.tournament.refresh_from_db()
        self.assertEqual(self.tournament.report_notes, "Επίσημες σημειώσεις")
        self.finish()
        self.accept(self.not_playing)
        self.assertEqual(self.client.post(notes_url, {"report_notes": "Edit after signing"}).status_code, 409)
        self.accept(self.player_b)
        self.assertIn("Επίσημες σημειώσεις", self.pdf_text())

    def test_two_page_score_sheet_for_larger_realistic_vs(self):
        self.finish()
        # Simulate a substantial completed VS sheet with actual lineups.
        for i in range(16):
            self.game(
                "tete_a_tete" if i % 3 == 0 else "doublet" if i % 3 == 1 else "triplet",
                2 if i % 3 == 0 else 3 if i % 3 == 1 else 5,
                [self.player_a] if i % 3 == 0 else [self.player_a, self.extra_a[0]]
                if i % 3 == 1 else [self.player_a, *self.extra_a],
                [self.player_b] if i % 3 == 0 else [self.player_b, self.extra_b[0]]
                if i % 3 == 1 else [self.player_b, *self.extra_b],
                13, 6, self.a,
            )
        self.sign_both()
        response = self.client.get(self.pdf_url)
        pages = PdfReader(BytesIO(response.content)).pages
        self.assertGreaterEqual(len(pages), 2)
        self.assertIn("ΨΗΦΙΑΚΗ ΕΠΙΚΥΡΩΣΗ", pages[-1].extract_text())

    def test_revision_before_final_attestation_invalidates_previous_approval(self):
        self.finish()
        self.accept(self.player_a)
        self.first.team1_score = 12
        self.first.save(update_fields=["team1_score"])
        # Revoked by the material change: an existing A signature is not enough.
        second = self.accept(self.player_b)
        self.assertFalse(second.json()["issued"])
        self.assertEqual(self.client.get(self.pdf_url).status_code, 409)
        first = self.accept(self.player_a)
        self.assertTrue(first.json()["issued"])

    def test_empty_final_qr_comment_defaults_to_all_well(self):
        self.finish()
        self.sign_both()
        self.assertEqual(
            VSSheetAttestation.objects.get(encounter=self.encounter, role="team1").remarks,
            "Όλα καλώς",
        )
        self.assertEqual(
            VSSheetAttestation.objects.get(encounter=self.encounter, role="team2").remarks,
            "Όλα καλώς",
        )
        self.assertIn("Παρατήρηση: Όλα καλώς", self.pdf_text())

    def test_custom_qr_comments_appear_with_correct_signer_in_frozen_pdf(self):
        self.finish()
        self.assertEqual(self.scan(self.not_playing).status_code, 200)
        comment = "Υπήρξε διακοπή λόγω βροχής. Συμφωνούμε με το τελικό αποτέλεσμα."
        response = self.client.post(
            self.attest_url,
            data=json.dumps({"remarks": comment}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["issued"])
        signer = VSSheetAttestation.objects.get(encounter=self.encounter, role="team1")
        self.assertEqual(signer.remarks, comment)
        self.assertEqual(signer.player, self.not_playing)
        self.accept(self.player_b)
        text = self.pdf_text()
        self.assertIn(comment, text)
        self.assertIn("Ανθή βοηθός", text)
        self.assertIn("Παρατήρηση: Όλα καλώς", text)

    def test_overlong_qr_comments_do_not_consume_scan_or_create_attestation(self):
        self.finish()
        self.scan(self.not_playing)
        rejected = self.client.post(
            self.attest_url,
            data=json.dumps({"remarks": "x" * 1001}),
            content_type="application/json",
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertFalse(VSSheetAttestation.objects.exists())
        accepted = self.client.post(
            self.attest_url,
            data=json.dumps({"remarks": ""}),
            content_type="application/json",
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(
            VSSheetAttestation.objects.get(encounter=self.encounter, role="team1").remarks,
            "Όλα καλώς",
        )

    def test_vs_sheet_ui_has_immediate_qr_remarks_and_single_confirmation(self):
        self.finish()
        rendered = self.client.get(self.page_url)
        self.assertEqual(rendered.status_code, 200)
        self.assertContains(rendered, 'window.QR_DIRECT_TO_VS_SHEET_REMARKS = true')
        self.assertContains(rendered, 'id="vs-sheet-remarks-text"')
        self.assertContains(rendered, 'ΟΚ · Επικύρωση')
        self.assertContains(rendered, 'Όλα καλώς')

    def _assert_court_timezone_in_sealed_sheet(self, instant_utc, expected_local_time, zone_name):
        """The actual QR acceptance must freeze a PDF with venue-local times."""
        court_complex = CourtComplex.objects.create(
            name="VS PDF clock test venue", description="Clock test",
            timezone_name=zone_name,
        )
        court = Court.objects.create(number=7001, name="Test VC1")
        court_complex.courts.add(court)
        for match in (self.first, self.doublet, self.triplet, self.pending):
            match.court = court
            match.save(update_fields=["court"])
        self.finish()

        # Keep canonical timestamps in UTC; localize only the PDF rendering.
        with patch("django.utils.timezone.now", return_value=instant_utc):
            issued = self.sign_both()
        self.assertTrue(issued.json()["issued"])
        self.assertEqual(
            VSSheetAttestation.objects.get(encounter=self.encounter, role="team1").attested_at,
            instant_utc,
        )
        pdf = self.pdf_text()
        self.assertIn(f"Επικυρώθηκε μέσω PFC QR · {expected_local_time}", pdf)
        self.encounter.refresh_from_db()
        self.assertEqual(self.client.get(self.pdf_url).content, bytes(self.encounter.sheet_pdf))

    def test_vs_sheet_qr_times_use_athens_summer_time(self):
        self._assert_court_timezone_in_sealed_sheet(
            datetime(2026, 7, 10, 12, 0, tzinfo=datetime_timezone.utc),
            "10/07/2026 15:00", "Europe/Athens",
        )

    def test_vs_sheet_qr_times_use_athens_winter_time(self):
        self._assert_court_timezone_in_sealed_sheet(
            datetime(2026, 1, 10, 12, 0, tzinfo=datetime_timezone.utc),
            "10/01/2026 14:00", "Europe/Athens",
        )

    def test_vs_sheet_qr_times_use_non_greek_venue_timezone(self):
        self._assert_court_timezone_in_sealed_sheet(
            datetime(2026, 7, 10, 12, 0, tzinfo=datetime_timezone.utc),
            "10/07/2026 08:00", "America/New_York",
        )

    def test_non_vs_report_is_not_generated(self):
        self.tournament.allowed_match_types = {}
        self.tournament.save(update_fields=["allowed_match_types"])
        self.assertEqual(self.client.get(self.pdf_url).status_code, 404)
