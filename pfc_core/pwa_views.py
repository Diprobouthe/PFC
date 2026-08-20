"""Optional Progressive Web App asset endpoints for PFC.

These endpoints are intentionally isolated from normal application views. The
manifest describes installation metadata, while the root-scoped service worker
only caches immutable static assets and never caches dynamic sporting data.
"""

from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@require_GET
@never_cache
def web_app_manifest(request):
    """Serve PFC's install metadata from a stable, root-level URL."""
    response = JsonResponse(
        {
            "id": "/",
            "name": "PFC",
            "short_name": "PFC",
            "description": "PFC — Pétanque France Club",
            "lang": "en",
            "dir": "ltr",
            "start_url": "/",
            "scope": "/",
            "display": "standalone",
            "display_override": ["standalone"],
            "theme_color": "#0d47a1",
            "background_color": "#0f172a",
            "categories": ["sports", "social", "events"],
            "icons": [
                {
                    "src": static("pwa/pfc-icon-192.png"),
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
                {
                    "src": static("pwa/pfc-icon-512.png"),
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any maskable",
                },
            ],
        },
        json_dumps_params={"ensure_ascii": False},
    )
    response["Content-Type"] = "application/manifest+json; charset=utf-8"
    return response


@require_GET
@never_cache
def service_worker(request):
    """Serve the worker at root scope so existing PFC deep links remain covered."""
    response = render(
        request,
        "pwa/service-worker.js",
        content_type="application/javascript; charset=utf-8",
    )
    response["Service-Worker-Allowed"] = "/"
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response
