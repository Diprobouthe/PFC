"""One lightweight, recoverable server clock for persisted Round deadlines.

This intentionally has no per-player and no per-Round timer. Every process may
notice a due Round after a restart; ``finalize_round_lineups`` serializes the
actual state change on the Round row, so duplicate clock processes are harmless.
"""

from __future__ import annotations

import logging
import threading
from datetime import timedelta

from django.db import close_old_connections
from django.utils import timezone

logger = logging.getLogger(__name__)
_wake_event = threading.Event()
_started = False
_start_lock = threading.Lock()


def wake_lineup_clock() -> None:
    """Wake the process-local clock after a newly committed Round is created."""
    _wake_event.set()


def _seconds_until_next_deadline() -> float:
    from tournaments.models import Round

    deadline = (
        Round.objects.filter(lineups_frozen_at__isnull=True, lineup_deadline_at__isnull=False)
        .order_by("lineup_deadline_at")
        .values_list("lineup_deadline_at", flat=True)
        .first()
    )
    if deadline is None:
        return 5.0
    return max(0.1, min(5.0, (deadline - timezone.now()).total_seconds()))


def _run() -> None:
    while True:
        try:
            close_old_connections()
            from tournaments.lineup_lifecycle import finalize_due_lineup_windows

            finalize_due_lineup_windows(limit=100)
            wait_seconds = _seconds_until_next_deadline()
        except Exception:
            logger.exception("Tournament Round lineup clock failed; it will retry")
            wait_seconds = 5.0
        finally:
            close_old_connections()

        _wake_event.wait(wait_seconds)
        _wake_event.clear()


def start_lineup_clock() -> None:
    """Start exactly one non-daemon clock per application process."""
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
        thread = threading.Thread(
            target=_run,
            name="pfc-tournament-lineup-clock",
            daemon=True,
        )
        thread.start()
        logger.info("Started Tournament Round lineup clock")
