"""Deterministic PETA series settlement, isolated from match/DB lifecycle.

The official PFC rating is never written here. Match deltas come from the
existing PFC calculator; award values and class weights are supplied by the
caller. This slice intentionally excludes task and production event hooks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from math import ceil
from typing import Mapping

from .peta_core import UNIT, decimal, distribute_pool, split_awards


@dataclass(frozen=True)
class EventPlayer:
    player_id: int
    prior_travel_points: object
    rating_delta: object
    awards: Mapping[str, object] = field(default_factory=dict)
    dividend_eligible: bool = False
    keep_all_now: bool = False
    exception_used_before: bool = False


def settle_event(
    players: list[EventPlayer],
    *,
    multiplier: object,
    middle_fraction: object = "0.70",
    top_fraction: object = "0.25",
    base_fraction: object = "0.35",
) -> dict:
    """Freeze pre-dividend ranks; split positive awards; conserve all points.

    Policy parameters are deliberately explicit; defaults are development
    candidates, not final event rules. No database I/O or live-page query.
    """
    if not players:
        raise ValueError("Empty PETA event")
    ids = [p.player_id for p in players]
    if any(not isinstance(pid, int) or pid <= 0 for pid in ids) or len(set(ids)) != len(ids):
        raise ValueError("Player IDs must be unique positive integers")
    m = decimal(multiplier)
    middle_share = decimal(middle_fraction)
    top_share = decimal(top_fraction)
    base_share = decimal(base_fraction)
    if m <= 0 or not 0 <= middle_share <= 1 or not 0 <= top_share < 1 or not 0 <= base_share < 1 or top_share + base_share >= 1:
        raise ValueError("Invalid PETA distribution policy")

    by_id = {p.player_id: p for p in players}
    splits, personal = {}, {}
    for p in players:
        if p.keep_all_now and p.exception_used_before:
            raise ValueError("One keep-all exception per player per series")
        split = split_awards(p.awards, keep_all=p.keep_all_now)
        splits[p.player_id] = split
        own_awards = sum((amount for _, amount in split.retained), Decimal(0))
        personal[p.player_id] = (
            decimal(p.prior_travel_points)
            + decimal(p.rating_delta) + (own_awards if p.keep_all_now else m * own_awards)
        ).quantize(UNIT, rounding=ROUND_HALF_UP)

    pool = (m * sum((s.pooled_total for s in splits.values()), Decimal(0))).quantize(
        UNIT, rounding=ROUND_HALF_UP
    )
    ranked = sorted(ids, key=lambda pid: (-personal[pid], pid))
    n = len(ids)
    top_count = ceil(n * top_share)
    base_count = min(ceil(n * base_share), n - top_count)
    top = ranked[:top_count]
    middle = ranked[top_count:n - base_count]
    base = ranked[n - base_count:]
    mid_eligible = [pid for pid in middle if by_id[pid].dividend_eligible]
    base_eligible = [pid for pid in base if by_id[pid].dividend_eligible]

    if mid_eligible and base_eligible:
        mid_pool = (pool * middle_share).quantize(UNIT, rounding=ROUND_HALF_UP)
        base_pool = pool - mid_pool
    elif mid_eligible:
        mid_pool, base_pool = pool, Decimal(0)
    elif base_eligible:
        mid_pool, base_pool = Decimal(0), pool
    else:
        mid_pool, base_pool = Decimal(0), Decimal(0)

    dividend = {pid: Decimal(0) for pid in ids}
    dividend.update(distribute_pool(mid_pool, {pid: 1 for pid in mid_eligible}))
    dividend.update(distribute_pool(base_pool, {pid: 1 for pid in base_eligible}))
    distributed = sum(dividend.values(), Decimal(0))
    if distributed > pool:
        raise AssertionError("Dividends exceed available pool")
    return {
        "rank_pre_dividend": ranked,
        "classes": {"top": top, "middle": middle, "base": base},
        "eligible": {"middle": mid_eligible, "base": base_eligible},
        "awards": splits,
        "pool": pool,
        "distributed": distributed,
        "undistributed": pool - distributed,
        "dividends": dividend,
        "personal_points": personal,
        "travel_points_after": {pid: personal[pid] + dividend[pid] for pid in ids},
    }
