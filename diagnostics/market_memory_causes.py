"""Identify Market object retention through the real Django/Daphne lifecycle."""
import gc
import json
import os
import weakref
import tracemalloc
from pathlib import Path

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "pfc_core.settings")
if os.environ.get("PFC_MARKET_DIAGNOSTIC") != "1":
    raise RuntimeError("Diagnostic opt-in required")

from pfc_core.asgi import application as real_application
from django.conf import settings
from django.http import HttpResponse
from django.db.models.fields.files import FieldFile
from teams import views_market as market

db = settings.DATABASES["default"]
if db["NAME"] != "pfc_market_memory_test" or db["HOST"] not in ("127.0.0.1", "localhost"):
    raise RuntimeError("Only the isolated loopback diagnostic database is permitted")

original_trend = market.calculate_player_trend
original_render = market.render
mode = "full"
tracking = False
refs = []
file_refs = []
edges = {}
variants = {"full", "orm_only", "break_orm", "break_image", "break_both"}

def trend(profile, *args, **kwargs):
    if tracking:
        # Inspect already-cached objects without invoking relationship descriptors.
        player = profile._state.fields_cache.get("player")
        if player is None:
            raise AssertionError("Expected select_related to populate player")
        refs.append((weakref.ref(profile), weakref.ref(player)))
        if player._state.fields_cache.get("profile") is profile:
            edges["orm_before_render"] += 1
    return original_trend(profile, *args, **kwargs)

def inspect_and_break():
    for profile_ref, player_ref in refs:
        profile, player = profile_ref(), player_ref()
        if profile is None or player is None:
            raise AssertionError("Fixture unexpectedly disappeared before render finished")
        if player._state.fields_cache.get("profile") is profile:
            edges["orm_after_render"] += 1
        picture = profile.__dict__.get("profile_picture")
        if isinstance(picture, FieldFile):
            file_refs.append(weakref.ref(picture))
            if picture.instance is profile:
                edges["image_self_cycle"] += 1
        # All intervention happens AFTER rendering, only in the test process.
        if mode in ("break_orm", "break_both"):
            if player._state.fields_cache.get("profile") is profile:
                player._state.fields_cache.pop("profile")
        if mode in ("break_image", "break_both"):
            if isinstance(picture, FieldFile):
                profile.__dict__["profile_picture"] = picture.name

def render(*args, **kwargs):
    if not tracking:
        return original_render(*args, **kwargs)
    response = (HttpResponse("ORM ONLY") if mode == "orm_only"
                else original_render(*args, **kwargs))
    inspect_and_break()
    return response

market.calculate_player_trend = trend
market.render = render

def sample():
    return {
        "mode": mode,
        "profiles_created": len(refs),
        "profiles_alive": sum(p() is not None for p, _ in refs),
        "players_alive": sum(p() is not None for _, p in refs),
        "fieldfiles_created": len(file_refs),
        "fieldfiles_alive": sum(f() is not None for f in file_refs),
        "edges": dict(edges),
        "rss_kib": int(next(l.split()[1] for l in Path("/proc/self/status").read_text().splitlines()
                            if l.startswith("VmRSS:"))),
        "python_current_bytes": tracemalloc.get_traced_memory()[0] if tracemalloc.is_tracing() else None,
        "gc_enabled": gc.isenabled(),
    }

async def application(scope, receive, send):
    global mode, tracking, refs, file_refs, edges
    path = scope.get("path", "")
    if scope["type"] != "http" or not path.startswith("/__cause_probe__/"):
        return await real_application(scope, receive, send)
    command = path.rstrip("/").rsplit("/", 1)[-1]
    if command in variants:
        tracking = False
        refs, file_refs = [], []
        edges = {"orm_before_render": 0, "orm_after_render": 0, "image_self_cycle": 0}
        gc.enable()
        gc.collect()
        if not tracemalloc.is_tracing():
            tracemalloc.start(5)
        mode = command
        # Deterministically isolate reference counting from cyclic GC.
        gc.disable()
        tracking = True
        result = sample()
    elif command == "before_gc":
        tracking = False
        result = sample()
    elif command == "after_gc":
        tracking = False
        collected = gc.collect()
        gc.enable()
        result = {**sample(), "gc_collected": collected}
    else:
        raise ValueError(command)
    body = json.dumps(result).encode()
    await send({"type":"http.response.start", "status":200,
                "headers":[(b"content-type", b"application/json")]})
    await send({"type":"http.response.body", "body":body})
