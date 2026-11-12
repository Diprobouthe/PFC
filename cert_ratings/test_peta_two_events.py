"""Minimal replay: exactly two synthetic Super Melee events, 12 players each.

This is not a Snake Draft or ORM lifecycle integration test. It does call the
actual PFC rating mathematics through PETA, unlike duplicated test equations.
No production data, no random seeds, no eight-event workload.
"""
import unittest
from decimal import Decimal

from cert_ratings.peta_core import pfc_match_delta, protected_entry_rating
from cert_ratings.peta_series import EventPlayer, settle_event

PLAYER_IDS = tuple(range(1, 13))
START_RATINGS = dict(zip(PLAYER_IDS, (182, 171, 160, 152, 146, 137, 130, 119, 112, 107, 99, 92)))


def replay_matches(entry, event_no):
    ratings = dict(entry)
    points_scored = dict.fromkeys(PLAYER_IDS, 0)
    wins = dict.fromkeys(PLAYER_IDS, 0)
    streak = dict.fromkeys(PLAYER_IDS, 0)
    best_streak = dict.fromkeys(PLAYER_IDS, 0)
    matches_played = 0
    for round_no in range(5):
        rotation = (round_no + event_no - 1) % len(PLAYER_IDS)
        roster = list(PLAYER_IDS[rotation:]) + list(PLAYER_IDS[:rotation])
        teams = [roster[i:i + 2] for i in range(0, 12, 2)]
        for game_no in range(3):
            team_a, team_b = teams[game_no * 2:game_no * 2 + 2]
            if 1 in team_a:
                a_wins = True
            elif 1 in team_b:
                a_wins = False
            else:
                a_wins = (event_no + round_no + game_no) % 2 == 0
            winner = team_a if a_wins else team_b
            losing_score = 9 + (event_no + round_no + game_no) % 4
            score_a, score_b = ((13, losing_score) if a_wins else (losing_score, 13))
            pre = ratings.copy()
            average_a = sum(pre[pid] for pid in team_a) / 2
            average_b = sum(pre[pid] for pid in team_b) / 2
            for members, opponent_avg, own_score, opponent_score in (
                (team_a, average_b, score_a, score_b),
                (team_b, average_a, score_b, score_a),
            ):
                for pid in members:
                    delta = pfc_match_delta(
                        own_rating=pre[pid],
                        opponent_average_rating=opponent_avg,
                        own_score=own_score,
                        opponent_score=opponent_score,
                    )
                    ratings[pid] = max(0, pre[pid] + delta)
                    points_scored[pid] += own_score
                    if pid in winner:
                        wins[pid] += 1
                        streak[pid] += 1
                        best_streak[pid] = max(best_streak[pid], streak[pid])
                    else:
                        streak[pid] = 0
            matches_played += 1
    return ratings, points_scored, wins, best_streak, matches_played


def provisional_awards(points, wins, streak):
    """Fixture values only; configuration is not yet a final event policy."""
    best_points = max(points.values())
    best_wins = max(wins.values())
    result = {}
    for pid in PLAYER_IDS:
        awards = {}
        if streak[pid] >= 5:
            awards['fires'] = 10
        elif streak[pid] == 4:
            awards['fires'] = 7
        elif streak[pid] == 3:
            awards['fires'] = 4
        if points[pid] == best_points:
            awards['top_points'] = 6
        if wins[pid] >= 4 and wins[pid] == best_wins:
            awards['best_win_rate'] = 6
        result[pid] = awards
    return result


def replay_exactly_two_events():
    travel = {pid: Decimal(0) for pid in PLAYER_IDS}
    previous_end = {}
    events = []
    for ordinal in (1, 2):
        if ordinal == 1:
            actual_pfc = START_RATINGS.copy()
        else:
            actual_pfc = previous_end.copy()
            actual_pfc[4] -= 35
            actual_pfc[2] += 12

        entry = {
            pid: protected_entry_rating(actual_pfc[pid], previous_end.get(pid))
            for pid in PLAYER_IDS
        }
        ratings, points, wins, streak, match_count = replay_matches(entry, ordinal)
        awards = provisional_awards(points, wins, streak)
        eligible = set(PLAYER_IDS) - {9, 12}
        if ordinal == 2:
            eligible.add(9)  # newly contributed tracked data

        inputs = [
            EventPlayer(
                player_id=pid,
                prior_travel_points=travel[pid],
                rating_delta=round(ratings[pid] - entry[pid], 2),
                awards=awards[pid],
                dividend_eligible=pid in eligible,
            )
            for pid in PLAYER_IDS
        ]
        result = settle_event(inputs, multiplier="1" if ordinal == 1 else "1.25")
        events.append({
            'ordinal': ordinal, 'current_pfc': actual_pfc, 'entry': entry,
            'end': ratings, 'awards': awards, 'eligible': eligible,
            'matches': match_count, 'result': result, 'inputs': inputs,
        })
        travel = result['travel_points_after']
        previous_end = ratings
    return events


class PetaTwoEventReplayTests(unittest.TestCase):
    def test_two_events_with_protected_entries_and_dividends(self):
        first, second = replay_exactly_two_events()
        self.assertEqual((first['matches'], second['matches']), (15, 15))
        self.assertEqual(first['result']['pool'], Decimal('12.0000'))
        self.assertEqual(second['result']['pool'], Decimal('15.0000'))

        self.assertAlmostEqual(second['current_pfc'][4], first['end'][4] - 35)
        self.assertAlmostEqual(second['entry'][4], first['end'][4])
        self.assertAlmostEqual(second['entry'][2], first['end'][2] + 12)

        for event in (first, second):
            result = event['result']
            self.assertEqual(result['pool'], result['distributed'] + result['undistributed'])
            self.assertEqual(result['undistributed'], 0)
            self.assertEqual(len(result['classes']['top']), 3)
            self.assertEqual(len(result['classes']['middle']), 4)
            self.assertEqual(len(result['classes']['base']), 5)
            self.assertTrue(all(result['dividends'][pid] == 0 for pid in result['classes']['top']))
            self.assertTrue(all(result['dividends'][pid] == 0 for pid in set(PLAYER_IDS) - event['eligible']))
            self.assertEqual(
                result, settle_event(event['inputs'],
                                     multiplier='1' if event['ordinal'] == 1 else '1.25')
            )
        self.assertFalse(first['eligible'].__contains__(9))
        self.assertTrue(second['eligible'].__contains__(9))

    def test_pool_is_recorded_but_not_minted_without_recipients(self):
        players = [
            EventPlayer(i, 0, 0, {'test_big': 9, 'test_small': 4} if i == 1 else {})
            for i in PLAYER_IDS
        ]
        result = settle_event(players, multiplier=1)
        self.assertEqual(result['pool'], Decimal('4.0000'))
        self.assertEqual(result['distributed'], 0)
        self.assertEqual(result['undistributed'], Decimal('4.0000'))

    def test_keep_all_cannot_be_reused(self):
        players = [EventPlayer(1, 0, 0, {'a': 10, 'b': 6},
                               dividend_eligible=True, keep_all_now=True)]
        self.assertEqual(settle_event(players, multiplier=1)['pool'], 0)
        players = [EventPlayer(1, 0, 0, {'a': 10, 'b': 6},
                               dividend_eligible=True, keep_all_now=True,
                               exception_used_before=True)]
        with self.assertRaises(ValueError):
            settle_event(players, multiplier=1)


if __name__ == '__main__':
    unittest.main()
