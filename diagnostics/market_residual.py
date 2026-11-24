"""Isolate residual allocations in the flat Market, only on a synthetic DB."""
import gc
import json
import os
import tracemalloc
from collections import Counter
from pathlib import Path

from diagnostics.market_flat_server import application as real_application
from diagnostics import market_flat_candidate as candidate
from django.http import HttpResponse
from django.template import engines
from teams.urls import urlpatterns

mode = os.environ.get("PFC_RESIDUAL_MODE", "full")
if os.environ.get("PFC_MARKET_VARIANT") != "flat":
    raise RuntimeError("Flat candidate required")
original_render = candidate.render
minimal = engines["django"].from_string("{{ market_data|length }}")
def render(request, template, context):
    if mode == "no_render":
        return HttpResponse("flat query only")
    if mode in ("minimal", "minimal_no_context"):
        return HttpResponse(minimal.render(context, request if mode == "minimal" else None))
    return original_render(request, template, context)
candidate.render = render
if mode == "django_empty":
    def empty(request):
        return HttpResponse("empty")
    next(p for p in urlpatterns if p.name == "pfc_market").callback = empty

def rss():
    return int(next(l.split()[1] for l in Path("/proc/self/status").read_text().splitlines()
                    if l.startswith("VmRSS:")))
def sample():
    return {"mode": mode, "rss_kib": rss(),
            "python_bytes": tracemalloc.get_traced_memory()[0] if tracemalloc.is_tracing() else None,
            "gc_counts": list(gc.get_count()), "gc_stats": gc.get_stats()}

def typename(o):
    t = type(o)
    return t.__module__ + "." + t.__qualname__

def garbage_report():
    # Only run after a single isolated request with automatic GC disabled.
    # SAVEALL is temporary; release all captured garbage immediately afterward.
    old = gc.get_debug()
    gc.set_debug(old | gc.DEBUG_SAVEALL)
    try:
        collected = gc.collect()
        objects = gc.garbage
        ids = {id(o) for o in objects}
        counts = Counter(typename(o) for o in objects)
        edges = Counter()
        allocations = Counter()
        for o in objects:
            source = typename(o)
            for target in gc.get_referents(o):
                if id(target) in ids:
                    edges[(source, typename(target))] += 1
            tb = tracemalloc.get_object_traceback(o)
            if tb:
                allocations[(source, str(tb[-1]))] += 1
        return {"collected": collected, "types": counts.most_common(30),
                "edges": [[a,b,n] for (a,b),n in edges.most_common(30)],
                "allocation_sites": [[a,b,n] for (a,b),n in allocations.most_common(30)]}
    finally:
        gc.set_debug(old)
        gc.garbage.clear()
        gc.enable()
        gc.collect()

async def application(scope, receive, send):
    path = scope.get("path", "")
    if scope["type"] == "http" and path.startswith("/__residual_probe__/"):
        action = path.rstrip("/").rsplit("/",1)[-1]
        if action == "start":
            gc.enable()
            gc.collect()
            if os.environ.get("PFC_RESIDUAL_TRACE") == "1":
                tracemalloc.start(8)
            result = sample()
        elif action == "isolate":
            gc.collect()
            gc.disable()
            result = sample()
        elif action == "garbage":
            result = garbage_report()
        elif action == "collect":
            gc.collect()
            result = sample()
        elif action == "sample":
            result = sample()
        else:
            raise ValueError(action)
        body = json.dumps(result).encode()
    elif mode == "raw" and scope["type"] == "http" and path == "/teams/players/pfc-market/":
        body = b"raw ASGI"
    else:
        return await real_application(scope, receive, send)
    await send({"type":"http.response.start","status":200,"headers":[(b"content-type",b"application/json")]})
    await send({"type":"http.response.body","body":body})
