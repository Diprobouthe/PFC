"""Focused HTTP regression for PETA Travel Points display (isolated test DB)."""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cert_ratings.models import CertifyingEntity
from cert_ratings.peta_models import PetaCompetitor, PetaEvent, PetaEventEntry, PetaSeries
from teams.models import Player, PlayerProfile, Team
from tournaments.models import Tournament


class PetaTravelPointsDisplayTests(TestCase):
    def setUp(self):
        self.team = Team.objects.create(name="Travel display test club")
        self.player = Player.objects.create(name="Travel NPC 13", team=self.team)
        self.other = Player.objects.create(name="Travel NPC 14", team=self.team)
        self.entity = CertifyingEntity.objects.create(
            name="Travel display test entity", rating_system="peta_algorithm"
        )
        self.series = PetaSeries.objects.create(name="Travel trip series", entity=self.entity)
        now = timezone.now()
        self.tournaments = [
            Tournament.objects.create(
                name=f"Travel meeting {n}", play_format="doublets",
                start_date=now, end_date=now + timedelta(hours=2),
                certifying_entity=self.entity,
            )
            for n in (1, 2, 3)
        ]
        self.events = [
            PetaEvent.objects.create(series=self.series, tournament=t, ordinal=n)
            for n, t in enumerate(self.tournaments, 1)
        ]
        PetaCompetitor.objects.create(
            series=self.series, player=self.player, travel_points=Decimal("23.7500")
        )
        PetaCompetitor.objects.create(
            series=self.series, player=self.other, travel_points=Decimal("6.0000")
        )
        for event, total, earned in [
            (self.events[0], "10.2500", "10.2500"),
            (self.events[2], "23.7500", "13.5000"),
        ]:
            PetaEventEntry.objects.create(
                event=event, player=self.player, entry_rating=100,
                end_rating=102, personal_earnings=Decimal(earned),
                dividend=Decimal("0"),
            )
            event.settled_at = now
            event.settlement_audit = {
                "travel_points_after": {str(self.player.pk): total}
            }
            event.save(update_fields=["settled_at", "settlement_audit"])
        PetaEventEntry.objects.create(
            event=self.events[2], player=self.other, entry_rating=100,
            end_rating=100, personal_earnings=Decimal("6"),
        )
        self.events[2].settlement_audit["travel_points_after"][str(self.other.pk)] = "6.0000"
        self.events[2].save(update_fields=["settlement_audit"])

    def test_profile_shows_plane_cumulative_points_and_only_played_events(self):
        response = self.client.get(reverse("player_profile", args=[self.player.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "fa-plane")
        self.assertContains(response, "23.75")
        self.assertContains(response, "13.50")
        self.assertContains(response, "Travel meeting 1")
        self.assertContains(response, "Travel meeting 3")
        self.assertNotContains(response, "Travel meeting 2")
        self.assertContains(response, "2 participations")

    def test_tournament_shows_settled_points_without_recomputing(self):
        response = self.client.get(
            reverse("tournament_detail", args=[self.tournaments[2].pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "fa-plane")
        self.assertContains(response, "Travel NPC 13")
        self.assertContains(response, "23.75")
        self.assertContains(response, "13.50")

    def test_unsettled_event_does_not_invent_points(self):
        response = self.client.get(
            reverse("tournament_detail", args=[self.tournaments[1].pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "after this PETA event is finalized")
        self.assertNotContains(response, "23.75")

    def test_non_peta_tournament_does_not_show_travel_points(self):
        now = timezone.now()
        ordinary = Tournament.objects.create(
            name="Ordinary tournament", play_format="doublets",
            start_date=now, end_date=now + timedelta(hours=2),
        )
        response = self.client.get(reverse("tournament_detail", args=[ordinary.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "PETA Travel Points")

    def test_private_profile_hides_travel_points(self):
        profile, _ = PlayerProfile.objects.get_or_create(player=self.player)
        profile.hide_public_statistics = True
        profile.save(update_fields=["hide_public_statistics"])
        response = self.client.get(reverse("player_profile", args=[self.player.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "PETA Travel Points")
        self.assertNotContains(response, "23.75")
