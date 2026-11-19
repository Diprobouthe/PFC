"""Four transparent, synthetic scenarios of the locked PETA settlement code.

No Django models, production data, tournament state changes or reimplementation
of reward mathematics. Use the actual main-branch PETA modules unchanged.
All scenario parameters and participation/eligibility assumptions are explicit.
"""
import unittest
from decimal import Decimal

from cert_ratings.peta_policy import (
    AWARDS, MULTIPLIERS, TOP_FRACTION, BASE_FRACTION, MIDDLE_SHARE
)
from cert_ratings.peta_series import EventPlayer, settle_event


PLAYER_IDS = tuple(range(1, 21))
# Player 1 is the main award winner; the other players have descending
# pre-existing travel points, yielding an observable 5 / 8 / 7 class split.
# The only badge combination is illustrative, not a claim about real players.
MAIN_AWARDS = {
    "fires": AWARDS["fire5"],                 # 10
    "top_points": AWARDS["top_points"],       # 6
    "best_win_rate": AWARDS["best_win_rate"], # 6
    "podium": AWARDS["podium1"],              # 3
}


def scenario(ordinal, *, keep_all=False, eligible_ids=range(6, 21)):
    """Call the actual settlement engine on a frozen 20-player snapshot.

    For Keep All scenarios, assume player 1 had 3 completed earlier events
    and selected Keep All before team generation. This isolated settlement
    test does NOT test the registration gate (existing Django tests do).
    """
    eligible = set(eligible_ids)
    players = [
        EventPlayer(
            player_id=pid,
            prior_travel_points=Decimal(201 - pid),
            rating_delta=Decimal("0"),
            awards=MAIN_AWARDS if pid == 1 else {},
            dividend_eligible=pid in eligible,
            keep_all_now=(pid == 1 and keep_all),
        )
        for pid in PLAYER_IDS
    ]
    return settle_event(
        players,
        multiplier=MULTIPLIERS[ordinal - 1],
        middle_fraction=MIDDLE_SHARE,
        top_fraction=TOP_FRACTION,
        base_fraction=BASE_FRACTION,
    )


class PetaLockedScenarioTests(unittest.TestCase):

    def test_01_fifth_event_keep_all_gains_five_but_removes_thirty_from_pool(self):
        standard = scenario(5)
        keep = scenario(5, keep_all=True)
        self.assertEqual(MULTIPLIERS[4], Decimal("2"))
        self.assertEqual(standard["personal_points"][1], Decimal("220.0000"))
        self.assertEqual(keep["personal_points"][1], Decimal("225.0000"))
        self.assertEqual(standard["pool"], Decimal("30.0000"))
        self.assertEqual(standard["distributed"], Decimal("30.0000"))
        self.assertEqual(keep["pool"], Decimal("0.0000"))
        self.assertEqual(keep["distributed"], Decimal("0.0000"))
        self.assertEqual(standard["classes"], keep["classes"])
        print("SIM_01 event=5 choice=standard_vs_keep_all personal_p1=220_vs_225 "
              "community_pool=30_vs_0")

    def test_02_eighth_event_keep_all_even_hurts_chooser(self):
        standard = scenario(8)
        keep = scenario(8, keep_all=True)
        self.assertEqual(MULTIPLIERS[7], Decimal("3"))
        self.assertEqual(standard["personal_points"][1], Decimal("230.0000"))
        self.assertEqual(keep["personal_points"][1], Decimal("225.0000"))
        self.assertEqual(standard["pool"], Decimal("45.0000"))
        self.assertEqual(keep["pool"], Decimal("0.0000"))
        self.assertEqual(standard["distributed"], Decimal("45.0000"))
        print("SIM_02 event=8 choice=standard_vs_keep_all personal_p1=230_vs_225 "
              "community_pool=45_vs_0")

    def test_03_fewer_eligible_players_concentrate_dividend_and_reverse_final_order(self):
        all_eligible = scenario(5)
        two_eligible = scenario(5, eligible_ids=(6, 14))
        self.assertEqual(two_eligible["rank_pre_dividend"], list(PLAYER_IDS))
        self.assertEqual(two_eligible["classes"], {
            "top": list(range(1, 6)),
            "middle": list(range(6, 14)),
            "base": list(range(14, 21)),
        })
        self.assertEqual(two_eligible["dividends"][6], Decimal("21.0000"))
        self.assertEqual(two_eligible["dividends"][14], Decimal("9.0000"))
        self.assertEqual(all_eligible["dividends"][6], Decimal("2.6250"))
        self.assertEqual(two_eligible["distributed"], Decimal("30.0000"))
        self.assertEqual(
            two_eligible["travel_points_after"][6], Decimal("216.0000")
        )
        self.assertGreater(
            two_eligible["travel_points_after"][6],
            two_eligible["travel_points_after"][2],
        )
        self.assertEqual(two_eligible["rank_pre_dividend"].index(6) + 1, 6)
        self.assertTrue(all(
            amount == 0 for pid, amount in two_eligible["dividends"].items()
            if pid not in (6, 14)
        ))
        print("SIM_03 event=5 eligible=15_vs_2 player6_dividend=2.625_vs_21 "
              "player6_pre_rank=6 final_travel_points=216")

    def test_04_zero_eligible_players_leave_pool_undistributed(self):
        nobody = scenario(5, eligible_ids=())
        self.assertEqual(nobody["pool"], Decimal("30.0000"))
        self.assertEqual(nobody["distributed"], Decimal("0"))
        self.assertEqual(nobody["undistributed"], Decimal("30.0000"))
        self.assertTrue(all(v == 0 for v in nobody["dividends"].values()))
        self.assertEqual(
            nobody["pool"], nobody["distributed"] + nobody["undistributed"]
        )
        print("SIM_04 event=5 eligible=0 pool=30 distributed=0 undistributed=30")


if __name__ == "__main__":
    unittest.main()
