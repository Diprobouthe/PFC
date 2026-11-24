"""Run unchanged or flat Market in a fresh isolated Daphne process."""
import os
from diagnostics.market_memory import application
if os.environ.get("PFC_MARKET_VARIANT") == "flat":
    from diagnostics.market_flat_candidate import pfc_market
    from teams.urls import urlpatterns
    matches = [pattern for pattern in urlpatterns if pattern.name == "pfc_market"]
    if len(matches) != 1:
        raise RuntimeError("Market URL not found")
    matches[0].callback = pfc_market
    print("FLAT_MARKET_ENABLED", flush=True)
