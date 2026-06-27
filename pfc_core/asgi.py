"""
ASGI config for pfc_core project.

Extends the default Django ASGI application with Django Channels so that
WebSocket connections are handled by the pfc_events and invites consumers
while all HTTP traffic continues through the standard Django request/response cycle.

SessionMiddlewareStack wraps the URLRouter so that self.scope["session"] is
populated from the browser's session cookie in every consumer.  This is
required for the InviteConsumer auth guard and also enables the
MatchEventConsumer personal-group feature (player_{codename}) to work
correctly when a player is logged in.
"""
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from channels.sessions import SessionMiddlewareStack

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pfc_core.settings')

# Must be called before importing any models or apps
django_asgi_app = get_asgi_application()

from pfc_events.routing import websocket_urlpatterns          # noqa: E402
from invites.routing import websocket_urlpatterns as invite_ws  # noqa: E402

# Merge all WebSocket URL patterns
all_ws_patterns = websocket_urlpatterns + invite_ws

application = ProtocolTypeRouter({
    # All HTTP requests go through the standard Django WSGI-compatible handler
    "http": django_asgi_app,
    # WebSocket connections are routed to the appropriate consumer.
    # SessionMiddlewareStack provides scope["session"] (read from the browser
    # session cookie) so consumers can authenticate the connecting player.
    "websocket": AllowedHostsOriginValidator(
        SessionMiddlewareStack(
            URLRouter(all_ws_patterns)
        )
    ),
})
