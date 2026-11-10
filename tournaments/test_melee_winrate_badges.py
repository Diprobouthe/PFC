"""Regression tests for exact Mêlée Best Win Rate badge comparisons."""

from types import SimpleNamespace

from django.test import SimpleTestCase

from tournaments.melee_leaderboard_view import calculate_melee_badges


def player_stats(player_id, wins, matches_played):
    """Minimal Mêlée stats with no competing non-win-rate badges."""
    return SimpleNamespace(
        player=SimpleNamespace(id=player_id),
        player_id=player_id,
        wins=wins,
        matches_played=matches_played,
        current_rating=100.0,
        starting_rating=100.0,
        best_performance=0,
        points_scored=0,
    )


def wins_winrate_badge(badges, player_id):
    return any(badge["type"] == "winrate" for badge in badges[player_id])


class MeleeBestWinRatePrecisionTests(SimpleTestCase):
    def test_non_terminating_ratios_still_win_badge(self):
        # Previous float-vs-rounded comparison dropped both awards.
        for wins, played in ((5, 6), (6, 7)):
            with self.subTest(wins=wins, played=played):
                badges = calculate_melee_badges([
                    player_stats(1, wins, played),
                    player_stats(2, 4, 5),
                ])
                self.assertTrue(wins_winrate_badge(badges, 1))
                self.assertFalse(wins_winrate_badge(badges, 2))

    def test_exact_ratio_ties_share_badge(self):
        badges = calculate_melee_badges([
            player_stats(1, 5, 6),
            player_stats(2, 10, 12),
            player_stats(3, 4, 5),
        ])
        self.assertTrue(wins_winrate_badge(badges, 1))
        self.assertTrue(wins_winrate_badge(badges, 2))
        self.assertFalse(wins_winrate_badge(badges, 3))

    def test_display_rounding_does_not_create_false_ties(self):
        # Both display as 83.3%, but 5/6 > 833/1000.
        badges = calculate_melee_badges([
            player_stats(1, 5, 6),
            player_stats(2, 833, 1000),
        ])
        self.assertTrue(wins_winrate_badge(badges, 1))
        self.assertFalse(wins_winrate_badge(badges, 2))

    def test_three_game_minimum_and_eighty_percent_threshold(self):
        badges = calculate_melee_badges([
            player_stats(1, 2, 2),  # 100% but ineligible
            player_stats(2, 4, 5),  # 80% and eligible
            player_stats(3, 3, 4),
        ])
        self.assertFalse(wins_winrate_badge(badges, 1))
        self.assertTrue(wins_winrate_badge(badges, 2))
        self.assertFalse(wins_winrate_badge(badges, 3))

    def test_no_award_if_best_eligible_ratio_is_below_eighty_percent(self):
        badges = calculate_melee_badges([
            player_stats(1, 3, 4),
            player_stats(2, 2, 3),
        ])
        self.assertFalse(wins_winrate_badge(badges, 1))
        self.assertFalse(wins_winrate_badge(badges, 2))
