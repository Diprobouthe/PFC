"""Read-only longitudinal summary for ordinary PFC practice sessions.

The series uses completed ordinary shooting and pointing sessions only; specialty
drills use different scoring and are deliberately excluded. Mean performance is
shot-weighted, variability describes session-to-session performance in percentage
points and is also weighted by sample size. No database writes or AI inference.
"""
from math import sqrt


WINDOW = 12
FIXED_DISTANCE_CODES = frozenset(("6m", "7m", "8m", "9m", "10m"))
SOURCE_MODES = ("all", "training", "ing")


def summarize_accuracy_views(sessions, window=WINDOW):
    """Three comparable scopes for the same two disciplines.

    'all' includes fixed-distance practice + in-game observations; other
    modes split by the stored distance field (not by is_active).
    """
    return {
        mode: summarize_practice_progress(sessions, window=window, mode=mode)
        for mode in SOURCE_MODES
    }


def summarize_practice_progress(sessions, window=WINDOW, mode="all"):
    """Return two small chart-ready series from PracticeSession model objects.

    The caller supplies newest-first sessions. Charts are chronological, and
    each percentage uses the existing PracticeSession.successful_shots rule.
    """
    if mode not in SOURCE_MODES:
        raise ValueError("Unknown accuracy observation source")
    result = {}
    for kind in ("shooting", "pointing"):
        eligible = [
            item for item in sessions
            if item.practice_type == kind
            and not item.is_active
            and item.ended_at is not None
            and item.drill_type in ("", "open")
            and item.total_shots > 0
            and (
                (mode == "all" and getattr(item, "distance", "7m") in FIXED_DISTANCE_CODES | {"ing"})
                or (mode == "training" and getattr(item, "distance", "7m") in FIXED_DISTANCE_CODES)
                or (mode == "ing" and getattr(item, "distance", "7m") == "ing")
            )
        ][:window]
        eligible.reverse()
        total_shots = sum(int(x.total_shots) for x in eligible)
        if not total_shots:
            result[kind] = {"count": 0, "total_shots": 0}
            continue

        points = [
            100.0 * max(0, min(int(x.successful_shots), int(x.total_shots))) / x.total_shots
            for x in eligible
        ]
        mean = sum(p * x.total_shots for p, x in zip(points, eligible)) / total_shots
        deviation = sqrt(
            sum(x.total_shots * (p - mean) ** 2 for p, x in zip(points, eligible)) / total_shots
        )
        # Fixed 0–100% axis so a visually steep slope always means a real
        # difference in percentage points, not automatic chart rescaling.
        n = len(points)
        xs = [10.0 + i * (280.0 / (n - 1)) if n > 1 else 150.0 for i in range(n)]
        ys = [90.0 - p * .80 for p in points]
        path = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
        baseline = 90.0 - mean * .80
        # Compare two non-overlapping recent 4-session windows; do not claim
        # a trend without sufficient history.
        trend = None
        if n >= 8:
            before = eligible[-8:-4]
            after = eligible[-4:]
            b_mean = sum(s.successful_shots for s in before) / sum(s.total_shots for s in before) * 100
            a_mean = sum(s.successful_shots for s in after) / sum(s.total_shots for s in after) * 100
            trend = round(a_mean - b_mean, 1)
        result[kind] = {
            "count": n,
            "total_shots": total_shots,
            "mean": round(mean, 1),
            "deviation": round(deviation, 1),
            "path": path,
            "average_y": round(baseline, 1),
            "trend": trend,
            "first": round(points[0], 1),
            "last": round(points[-1], 1),
        }
    return result
