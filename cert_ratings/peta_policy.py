"""PETA experimental reward policy.

Deliberately separate from the PFC rating mathematics. These values are
development candidates, not a claim that every rule is ratified.
"""
from decimal import Decimal

AWARDS = {
    "top_points": Decimal("6"),
    "best_win_rate": Decimal("6"),
    "fire3": Decimal("4"),
    "fire4": Decimal("7"),
    "fire5": Decimal("10"),
    "podium1": Decimal("3"),
    "podium2": Decimal("2"),
    "podium3": Decimal("1"),
}
MULTIPLIERS = (
    Decimal("1"), Decimal("1.25"), Decimal("1.5"), Decimal("1.75"),
    Decimal("2"), Decimal("2.25"), Decimal("2.5"), Decimal("3"),
)
TOP_FRACTION = Decimal("0.25")
BASE_FRACTION = Decimal("0.35")
MIDDLE_SHARE = Decimal("0.70")
MIN_WIN_RATE_MATCHES = 3
MIN_WIN_RATE = Decimal("0.80")


def awards_for_player(*, best_streak: int, top_points: bool,
                      best_win_rate: bool, podium_rank=None, include_podium=False):
    awards = {}
    if best_streak >= 5:
        awards["fires"] = AWARDS["fire5"]
    elif best_streak >= 4:
        awards["fires"] = AWARDS["fire4"]
    elif best_streak >= 3:
        awards["fires"] = AWARDS["fire3"]
    if top_points:
        awards["top_points"] = AWARDS["top_points"]
    if best_win_rate:
        awards["best_win_rate"] = AWARDS["best_win_rate"]
    if include_podium and podium_rank in (1, 2, 3):
        awards["podium"] = AWARDS[f"podium{podium_rank}"]
    return awards
