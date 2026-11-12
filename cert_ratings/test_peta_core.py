"""Non-production PETA scaffolding tests. No secret experimental policy here."""
import unittest
from decimal import Decimal

from cert_ratings.peta_core import (
    distribute_pool, pfc_match_delta, protected_entry_rating, split_awards,
)


class PetaPolicyNeutralCoreTests(unittest.TestCase):
    def test_entry_protection(self):
        self.assertEqual(protected_entry_rating(84, 116), 116)
        self.assertEqual(protected_entry_rating(142, 116), 142)
        self.assertEqual(protected_entry_rating(123), 123)

    def test_entry_rejects_invalid(self):
        for value in (-1, float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                protected_entry_rating(value)

    def test_keep_largest_and_pool_rest(self):
        awards = {'sample_c': '9', 'sample_b': '4', 'sample_a': '2'}
        split = split_awards(awards)
        self.assertEqual(split.retained, (('sample_c', Decimal(9)),))
        self.assertEqual(split.pooled_total, Decimal(6))
        self.assertEqual(sum((v for _, v in split.retained), Decimal(0)) + split.pooled_total,
                         Decimal(15))

    def test_keep_all_requires_explicit_flag(self):
        split = split_awards({'b': 3, 'a': 7}, keep_all=True)
        self.assertEqual(len(split.retained), 2)
        self.assertEqual(split.pooled_total, 0)

    def test_deterministic_ties(self):
        split = split_awards({'z': 8, 'a': 8})
        self.assertEqual(split.retained[0][0], 'a')

    def test_weights_and_conservation(self):
        shares = distribute_pool('6.0000', {7: 3, 8: 1})
        self.assertEqual(shares[7], Decimal('4.5000'))
        self.assertEqual(shares[8], Decimal('1.5000'))
        self.assertEqual(sum(shares.values()), Decimal('6.0000'))

    def test_indivisible_remainder_is_not_lost(self):
        shares = distribute_pool('1.0000', {1: 1, 2: 1, 3: 1})
        self.assertEqual(sum(shares.values()), Decimal('1.0000'))
        self.assertTrue(all(v >= 0 for v in shares.values()))
        self.assertEqual(shares, distribute_pool('1.0000', {3: 1, 1: 1, 2: 1}))

    def test_missing_recipients_and_bad_inputs(self):
        self.assertEqual(distribute_pool(0, {}), {})
        with self.assertRaises(ValueError):
            distribute_pool(1, {})
        with self.assertRaises(ValueError):
            distribute_pool('1.00005', {1: 1})
        with self.assertRaises(ValueError):
            distribute_pool(2, {1: -1})
        with self.assertRaises(ValueError):
            split_awards({'bad': -2})

    def test_delegates_to_existing_pfc_math(self):
        # Requires the real PFC Django runtime, exercised by GitHub Actions.
        from teams.models import PlayerProfile
        own_rating, opponent_rating, own, opp = 124.0, 115.0, 13, 7
        expected = PlayerProfile(value=own_rating).calculate_rating_change(
            opponent_value=opponent_rating, own_score=own, opponent_score=opp)
        self.assertEqual(pfc_match_delta(own_rating=own_rating,
                                         opponent_average_rating=opponent_rating,
                                         own_score=own, opponent_score=opp), expected)


if __name__ == '__main__':
    unittest.main()
