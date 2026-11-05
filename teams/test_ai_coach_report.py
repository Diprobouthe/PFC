"""Regression coverage for AI Coach Report computations.

These tests use only in-memory records: no production data and no DB writes.
"""
from types import SimpleNamespace

from django.test import SimpleTestCase

from teams.views_ai_report import (
    _aggregate_friendly_teammates,
    _compute_match_flow,
    _rating_delta_for_tournament_match,
    _verified_score_updates,
)


class CoachReportScoreFlowTests(SimpleTestCase):
    def test_post_match_reset_is_not_treated_as_result(self):
        updates = [
            {'team1_score': 0, 'team2_score': 0},
            {'team1_score': 4, 'team2_score': 4},
            {'team1_score': 9, 'team2_score': 5},
            {'team1_score': 0, 'team2_score': 0, 'update_type': 'correction'},
        ]
        history = _verified_score_updates(updates, 9, 5)
        self.assertEqual(history[-1]['team1_score'], 9)
        self.assertEqual(len(history), 3)
        flow = _compute_match_flow(history, 'team1')
        self.assertTrue(flow['player_won'])
        self.assertFalse(flow['lost_after_leading'])
        self.assertFalse(flow['close_finish'])
        self.assertEqual(flow['final_margin'], 4)

    def test_missing_official_final_omits_unverifiable_flow(self):
        updates = [{'team1_score': 3, 'team2_score': 2}]
        self.assertEqual(_verified_score_updates(updates, 13, 9), [])

    def test_same_score_correction_keeps_last_official_occurrence(self):
        updates = [
            {'team1_score': 9, 'team2_score': 5},
            {'team1_score': 1, 'team2_score': 1},
            {'team1_score': 9, 'team2_score': 5},
            {'team1_score': 0, 'team2_score': 0},
        ]
        self.assertEqual(len(_verified_score_updates(updates, 9, 5)), 3)


class CoachReportRatingAttributionTests(SimpleTestCase):
    def test_exact_match_id_prevents_time_based_misattribution(self):
        history = [
            {'match_id': 'friendly_90', 'match_type': 'tournament', 'change': 4.5},
            {'match_id': 42, 'match_type': 'tournament', 'change': -1.25},
            {'match_id': 42, 'match_type': 'friendly', 'change': 7.0},
        ]
        self.assertEqual(_rating_delta_for_tournament_match(history, 42), -1.25)
        self.assertIsNone(_rating_delta_for_tournament_match(history, 90))


class CoachReportFriendlyTeammateTests(SimpleTestCase):
    @staticmethod
    def mate(game_id, player_id, name, team='BLACK', verified=True, position='TIRER'):
        return SimpleNamespace(
            game_id=game_id, player_id=player_id,
            player=SimpleNamespace(name=name), team=team,
            codename_verified=verified, position=position,
        )

    def test_only_verified_same_side_teammates_are_counted(self):
        friendlies = [
            {'game_id': 1, 'team': 'BLACK', 'black_score': 13,
             'white_score': 7, 'position': 'POINTEUR'},
            {'game_id': 2, 'team': 'BLACK', 'black_score': 13,
             'white_score': 9, 'position': 'POINTEUR'},
            {'game_id': 3, 'team': 'BLACK', 'black_score': 8,
             'white_score': 13, 'position': 'MILIEU'},
            {'game_id': 4, 'team': 'WHITE', 'black_score': 13,
             'white_score': 13, 'position': 'POINTEUR'},
        ]
        roster = [
            self.mate(1, 22, 'Teammate'),
            self.mate(2, 22, 'Teammate'),
            self.mate(3, 22, 'Teammate'),
            self.mate(1, 23, 'Opposition', team='WHITE'),
            self.mate(2, 24, 'Unverified', verified=False),
            self.mate(3, 11, 'Self'),
            self.mate(4, 22, 'Teammate'),
        ]
        stats = _aggregate_friendly_teammates(11, friendlies, roster)
        self.assertEqual(len(stats), 1)
        self.assertEqual(stats[0]['name'], 'Teammate')
        self.assertEqual(stats[0]['games'], 3)
        self.assertEqual(stats[0]['wins'], 2)
        self.assertEqual(stats[0]['score_diff_total'], 5)  # +6 +4 -5
        self.assertEqual(stats[0]['roles']['POINTEUR / TIRER'], 2)
        self.assertEqual(stats[0]['roles']['MILIEU / TIRER'], 1)

    def test_teammates_with_same_name_remain_separate(self):
        friendly = [{'game_id': 1, 'team': 'WHITE', 'black_score': 4,
                     'white_score': 13, 'position': 'MILIEU'}]
        roster = [
            self.mate(1, 21, 'Alex', team='WHITE'),
            self.mate(1, 22, 'Alex', team='WHITE'),
        ]
        self.assertEqual(len(_aggregate_friendly_teammates(11, friendly, roster)), 2)
