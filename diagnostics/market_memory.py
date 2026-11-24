"""Isolated PFC Market RSS diagnostic. Never run with production data."""
import asyncio
import contextvars
import ctypes
import gc
import json
import os
import sys
import threading
import time
import tracemalloc
from collections import Counter
from datetime import timedelta
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pfc_core.settings")
if os.environ.get("PFC_MARKET_DIAGNOSTIC") != "1":
    raise RuntimeError("Diagnostic opt-in required")

def guard_db():
    from django.conf import settings
    db = settings.DATABASES["default"]
    if db["NAME"] != "pfc_market_memory_test" or db["HOST"] not in ("127.0.0.1", "localhost"):
        raise RuntimeError("Only the isolated loopback diagnostic database is permitted")

def seed():
    import django
    django.setup()
    guard_db()
    from django.utils import timezone
    from teams.models import Team, Player, PlayerProfile
    if Player.objects.exists():
        raise RuntimeError("Expected a fresh synthetic database")
    team = Team.objects.create(name="Synthetic Market", pin="MEM001")
    players = Player.objects.bulk_create([
        Player(name=f"Synthetic Player {i:03}", team=team)
        for i in range(300)
    ])
    now = timezone.now()
    PlayerProfile.objects.bulk_create([
        PlayerProfile(player=p, value=100 + i / 5, rating_history=[
            {"timestamp": (now - timedelta(hours=12 * (49-j))).isoformat(),
             "change": 1 if j % 2 else -1, "old_value": 100,
             "new_value": 101 if j % 2 else 99}
            for j in range(50)
        ])
        for i, p in enumerate(players)
    ])
    print(f"Seeded {PlayerProfile.objects.count()} profiles, 50 entries each", flush=True)

def rss_kib():
    return int(next(line.split()[1] for line in Path("/proc/self/status").read_text().splitlines()
                    if line.startswith("VmRSS:")))

def sample(stage):
    current, peak = tracemalloc.get_traced_memory() if tracemalloc.is_tracing() else (None, None)
    result = {"stage": stage, "rss_kib": rss_kib(), "python_current_bytes": current,
              "python_peak_bytes": peak, "threads": threading.active_count(),
              "gc_counts": list(gc.get_count()), "time": time.monotonic()}
    try:
        result["async_tasks"] = len(asyncio.all_tasks())
    except RuntimeError:
        pass
    print("MARKET_MEMORY " + json.dumps(result), flush=True)
    return result

if __name__ == "__main__":
    seed()
else:
    from pfc_core.asgi import application as real_application
    guard_db()
    from teams import views_market as market
    request_state = contextvars.ContextVar("market_probe_state", default=None)
    original_trend = market.calculate_player_trend
    original_render = market.render

    def trend(*args, **kwargs):
        state = request_state.get()
        if state is not None and not state["first"]:
            state["first"] = True
            sample("queryset_evaluated_first_trend")
        return original_trend(*args, **kwargs)

    def render(*args, **kwargs):
        if request_state.get() is not None:
            sample("trends_done_before_render")
        response = original_render(*args, **kwargs)
        if request_state.get() is not None:
            sample("html_rendered")
        return response

    market.calculate_player_trend = trend
    market.render = render

    async def application(scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] == "http" and path.startswith("/__memory_probe__/"):
            action = path.rstrip("/").rsplit("/", 1)[-1]
            if action == "trace":
                tracemalloc.start(5)
            if action == "gc":
                gc.collect()
            if action == "trim":
                ctypes.CDLL("libc.so.6").malloc_trim(0)
            if action == "snapshot":
                if not tracemalloc.is_tracing():
                    raise RuntimeError("tracing not enabled")
                snapshot = tracemalloc.take_snapshot()
                result = {"top": [str(s) for s in snapshot.statistics("lineno")[:20]]}
                del snapshot
            else:
                result = sample("probe_" + action)
            if action == "gc":
                # Counts only, without retaining the objects.
                types = Counter(type(o).__name__ for o in gc.get_objects())
                result["tracked_types"] = dict(types.most_common(20))
            body = json.dumps(result).encode()
            await send({"type":"http.response.start","status":200,
                        "headers":[(b"content-type", b"application/json")]})
            await send({"type":"http.response.body","body":body})
            return
        if scope["type"] != "http" or path != "/teams/players/pfc-market/":
            return await real_application(scope, receive, send)
        token = request_state.set({"first": False})
        sample("http_start")
        async def traced_send(message):
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body"):
                sample("response_sent")
        try:
            await real_application(scope, receive, traced_send)
        finally:
            sample("asgi_return")
            request_state.reset(token)
