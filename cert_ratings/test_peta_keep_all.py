"""Keep All is a player-owned decision made before roster freeze."""
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cert_ratings.models import CertifyingEntity
from cert_ratings.peta_keep_all import keep_all_state, set_keep_all_choice
from cert_ratings.peta_models import PetaCompetitor, PetaEvent, PetaEventEntry, PetaKeepAllChoice, PetaSeries
from cert_ratings.peta_service import freeze_peta_entries
from friendly_games.models import PlayerCodename
from teams.models import Player, Team
from tournaments.models import MeleePlayer, Tournament


class KeepAllPrestartTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Keep All club")
        self.player = Player.objects.create(name="Keep All player", team=self.team)
        self.other = Player.objects.create(name="Other player", team=self.team)
        self.entity = CertifyingEntity.objects.create(
            name="Keep All entity", rating_system="peta_algorithm"
        )
        self.series = PetaSeries.objects.create(name="Keep All series", entity=self.entity)
        now = timezone.now()
        self.tournament = Tournament.objects.create(
            name="Keep All meeting", play_format="doublets",
            start_date=now, end_date=now + timedelta(hours=3),
            is_melee=True, melee_format="doublets",
            certifying_entity=self.entity,
        )
        self.event = PetaEvent.objects.create(
            series=self.series, tournament=self.tournament, ordinal=1
        )
        self.registration = MeleePlayer.objects.create(
            tournament=self.tournament, player=self.player
        )

    def test_registration_required(self):
        with self.assertRaisesRegex(ValueError, "Register"):
            set_keep_all_choice(self.tournament.pk, self.other.pk, True)

    def test_prestart_selection_can_be_cancelled(self):
        set_keep_all_choice(self.tournament.pk, self.player.pk, True)
        self.assertTrue(keep_all_state(self.tournament, self.player)["enabled"])
        set_keep_all_choice(self.tournament.pk, self.player.pk, False)
        self.assertFalse(keep_all_state(self.tournament, self.player)["enabled"])

    def test_selection_is_frozen_into_event_entry(self):
        set_keep_all_choice(self.tournament.pk, self.player.pk, True)
        freeze_peta_entries(self.tournament, [self.registration])
        entry = PetaEventEntry.objects.get(event=self.event, player=self.player)
        self.assertTrue(entry.use_exception)
        with self.assertRaisesRegex(ValueError, "locked"):
            set_keep_all_choice(self.tournament.pk, self.player.pk, False)

    def test_no_selection_defaults_to_standard_awards(self):
        freeze_peta_entries(self.tournament, [self.registration])
        self.assertFalse(
            PetaEventEntry.objects.get(event=self.event, player=self.player).use_exception
        )

    def test_teams_generated_closes_choice_even_without_entries(self):
        self.tournament.melee_teams_generated = True
        self.tournament.save(update_fields=["melee_teams_generated"])
        with self.assertRaisesRegex(ValueError, "locked"):
            set_keep_all_choice(self.tournament.pk, self.player.pk, True)

    def test_used_exception_cannot_be_selected_again(self):
        PetaCompetitor.objects.create(
            series=self.series, player=self.player, exception_used=True
        )
        with self.assertRaisesRegex(ValueError, "already been used"):
            set_keep_all_choice(self.tournament.pk, self.player.pk, True)

    def test_second_meeting_cannot_be_reserved_while_first_selected(self):
        set_keep_all_choice(self.tournament.pk, self.player.pk, True)
        later = Tournament.objects.create(
            name="Second Keep All meeting", play_format="doublets",
            start_date=timezone.now(), end_date=timezone.now() + timedelta(hours=3),
            is_melee=True, melee_format="doublets", certifying_entity=self.entity,
        )
        PetaEvent.objects.create(series=self.series, tournament=later, ordinal=2)
        MeleePlayer.objects.create(tournament=later, player=self.player)
        with self.assertRaisesRegex(ValueError, "already selected"):
            set_keep_all_choice(later.pk, self.player.pk, True)

    def test_post_requires_authenticated_player_session(self):
        url = reverse("tournament_peta_keep_all", args=[self.tournament.pk])
        response = self.client.post(url, {"keep_all": "yes"})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(PetaKeepAllChoice.objects.exists())
        codename, _ = PlayerCodename.objects.get_or_create(player=self.player)
        session = self.client.session
        session["player_codename"] = codename.codename
        session["session_active"] = True
        session.save()
        response = self.client.post(url, {"keep_all": "yes"})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(PetaKeepAllChoice.objects.get(
            event=self.event, player=self.player
        ).enabled)
        response = self.client.get(reverse(
            "tournament_register_melee", args=[self.tournament.pk]
        ))
        self.assertContains(response, "Activate Keep All", count=0)
        self.assertContains(response, "Cancel selection before lock")
