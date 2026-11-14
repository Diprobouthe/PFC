"""Regression tests for mandatory podium 3/2/1 and unscaled rating delta."""
from decimal import Decimal
from django.test import SimpleTestCase

from cert_ratings.peta_policy import awards_for_player
from cert_ratings.peta_series import EventPlayer, settle_event
from cert_ratings.peta_models import PetaEvent


class PetaPodiumAndMultiplierTests(SimpleTestCase):
    def test_podium_awards_are_on_by_default(self):
        self.assertEqual(PetaEvent._meta.get_field("include_podium").default, True)
        for rank, expected in ((1, 3), (2, 2), (3, 1)):
            self.assertEqual(
                awards_for_player(best_streak=0, top_points=False,
                                  best_win_rate=False, podium_rank=rank)["podium"],
                Decimal(expected),
            )

    def test_rating_delta_not_multiplied_and_podium_goes_to_pool(self):
        players = [
            EventPlayer(player_id=1, prior_travel_points=0, rating_delta=8,
                        awards=awards_for_player(best_streak=5, top_points=True,
                                                 best_win_rate=True, podium_rank=1)),
            EventPlayer(player_id=2, prior_travel_points=0, rating_delta=0),
            EventPlayer(player_id=3, prior_travel_points=0, rating_delta=0),
            EventPlayer(player_id=4, prior_travel_points=0, rating_delta=0),
        ]
        result = settle_event(players, multiplier=3)
        self.assertEqual(result["personal_points"][1], Decimal("38.0000"))
        self.assertEqual(result["pool"], Decimal("45.0000"))
        self.assertEqual(result["awards"][1].pooled_total, Decimal(15))
