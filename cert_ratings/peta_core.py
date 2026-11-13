"""PETA Certified Entity: policy-neutral rating and redistribution primitives.

This module intentionally contains NO event rules, award values, eligibility
thresholds, category boundaries, or distribution percentages. Those are supplied
by a separately committed policy artifact at runtime. No database access here.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from math import isfinite
from typing import Mapping


UNIT = Decimal('0.0001')


def decimal(value) -> Decimal:
    """Convert numeric inputs to exact decimal strings; reject non-finite values."""
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('PETA inputs must be finite')
    return result


def protected_entry_rating(current_pfc_rating: float, previous_peta_end_rating: float | None = None) -> float:
    """Start from current PFC; ignore an intervening drop since previous PETA end."""
    current = float(current_pfc_rating)
    if not isfinite(current) or current < 0:
        raise ValueError('Current PFC rating must be finite and non-negative')
    if previous_peta_end_rating is None:
        return current
    previous = float(previous_peta_end_rating)
    if not isfinite(previous) or previous < 0:
        raise ValueError('Previous PETA rating must be finite and non-negative')
    return max(current, previous)


def pfc_match_delta(*, own_rating: float, opponent_average_rating: float,
                    own_score: int, opponent_score: int) -> float:
    """Delegate to the *existing* PFC calculation, without writing a PlayerProfile.

    The caller is responsible for supplying one consistent, pre-match rating
    snapshot for both teams and for persisting results exactly once in the
    PETA Certified Entity namespace. PFC global rating remains untouched here.
    """
    from teams.models import PlayerProfile

    probe = PlayerProfile(value=own_rating)  # unsaved, never .save()
    return probe.calculate_rating_change(
        opponent_value=opponent_average_rating,
        own_score=own_score,
        opponent_score=opponent_score,
    )


def peta_team_match_delta(*, own_team_ratings, opponent_team_ratings,
                          own_score: int, opponent_score: int) -> float:
    """One PETA rating change shared by every member of a doubles team.

    Compare the teams' PRE-match average ratings using the existing PFC
    score-difference formula. Do not use a player's individual rating in
    the ratio. This does not mutate the global PFC rating.
    """
    own = tuple(float(value) for value in own_team_ratings)
    opponent = tuple(float(value) for value in opponent_team_ratings)
    if len(own) != 2 or len(opponent) != 2:
        raise ValueError("PETA team rating requires two players per side")
    if any(not isfinite(value) or value < 0 for value in own + opponent):
        raise ValueError("PETA team ratings must be finite and non-negative")
    return pfc_match_delta(
        own_rating=sum(own) / 2,
        opponent_average_rating=sum(opponent) / 2,
        own_score=own_score,
        opponent_score=opponent_score,
    )


@dataclass(frozen=True)
class AwardSplit:
    retained: tuple[tuple[str, Decimal], ...]
    pooled: tuple[tuple[str, Decimal], ...]

    @property
    def pooled_total(self) -> Decimal:
        return sum((value for _, value in self.pooled), Decimal(0))


def split_awards(awards: Mapping[str, object], *, keep_all: bool = False) -> AwardSplit:
    """Keep the highest award (or all if explicitly authorized); pool the rest.

    This is a generic mechanism. This module does not decide when the player
    may invoke an exception, nor which awards have which values.
    """
    normalized = []
    for award_code, raw in awards.items():
        value = decimal(raw)
        if value < 0:
            raise ValueError('Award values cannot be negative')
        if value > 0:
            normalized.append((str(award_code), value))
    normalized.sort(key=lambda item: (-item[1], item[0]))
    retained = normalized if keep_all else normalized[:1]
    pooled = [] if keep_all else normalized[1:]
    return AwardSplit(tuple(retained), tuple(pooled))


def distribute_pool(pool: object, recipient_weights: Mapping[int, object]) -> dict[int, Decimal]:
    """Deterministically distribute a pool to externally selected recipients.

    No recipient classification or eligibility logic exists here. Caller passes
    only recipients authorized by private policy; their positive weights are
    supplied by the same policy. Conserve pool exactly at 4-decimal precision.
    """
    total = decimal(pool)
    if total < 0 or total != total.quantize(UNIT):
        raise ValueError('Pool must be non-negative and quantized to 0.0001')
    weights: dict[int, Decimal] = {}
    for player_id, raw in recipient_weights.items():
        if not isinstance(player_id, int) or player_id <= 0:
            raise ValueError('Player IDs must be positive integers')
        weight = decimal(raw)
        if weight < 0:
            raise ValueError('Recipient weights cannot be negative')
        if weight > 0:
            weights[player_id] = weight
    if not weights:
        if total:
            raise ValueError('Cannot distribute a nonzero pool without recipients')
        return {}
    denominator = sum(weights.values(), Decimal(0))
    sorted_ids = sorted(weights)
    remaining = total
    result = {}
    for player_id in sorted_ids[:-1]:
        amount = (total * weights[player_id] / denominator).quantize(UNIT, rounding=ROUND_HALF_UP)
        amount = min(amount, remaining)
        result[player_id] = amount
        remaining -= amount
    result[sorted_ids[-1]] = remaining
    return result
