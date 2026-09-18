from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods
from teams.utils import get_team_info_from_session
from teams.models import PlayerProfile
from billboard.analytics_utils import get_current_occupancy
from billboard.presence_prefs import UserPresencePrefs
from courts.models import CourtComplex
from friendly_games.court_utils import SESSION_PREF_COMPLEX_KEY
from matches.models import LiveScoreboard
import requests


HOME_WEATHER_CACHE_KEY = 'pfc:home-weather:current:v1'
HOME_WEATHER_LAST_SUCCESS_CACHE_KEY = 'pfc:home-weather:last-success:v1'
HOME_WEATHER_REFRESH_LOCK_KEY = 'pfc:home-weather:refresh-lock:v1'
HOME_WEATHER_CACHE_SECONDS = 60 * 60
HOME_WEATHER_LAST_SUCCESS_SECONDS = 24 * 60 * 60
HOME_WEATHER_REFRESH_LOCK_SECONDS = 15


def _fetch_home_weather():
    """Fetch and normalize the supplementary Home weather payload.

    The helper is deliberately called only by ``home_weather`` after Home has
    rendered. A malformed upstream payload is treated the same as an upstream
    request failure so callers can safely return cached last-success data.
    """
    response = requests.get(
        'https://api.open-meteo.com/v1/forecast',
        params={
            'latitude': 37.9908,
            'longitude': 23.7383,
            'current': 'temperature_2m,weather_code,wind_speed_10m',
            'timezone': 'Europe/Athens',
        },
        timeout=5,
    )
    response.raise_for_status()
    current = response.json().get('current')
    if not isinstance(current, dict) or current.get('temperature_2m') is None:
        raise ValueError('Open-Meteo response did not include a current temperature.')

    weather_descriptions = {
        0: ('Clear sky', '☀️'),
        1: ('Mainly clear', '🌤️'),
        2: ('Partly cloudy', '⛅'),
        3: ('Overcast', '☁️'),
        45: ('Foggy', '🌫️'),
        48: ('Foggy', '🌫️'),
        51: ('Light drizzle', '🌦️'),
        53: ('Moderate drizzle', '🌦️'),
        55: ('Dense drizzle', '🌧️'),
        61: ('Slight rain', '🌧️'),
        63: ('Moderate rain', '🌧️'),
        65: ('Heavy rain', '🌧️'),
        71: ('Slight snow', '🌨️'),
        73: ('Moderate snow', '🌨️'),
        75: ('Heavy snow', '❄️'),
        95: ('Thunderstorm', '⛈️'),
    }
    try:
        weather_code = int(current.get('weather_code', -1))
        temperature = round(float(current['temperature_2m']))
    except (TypeError, ValueError) as exc:
        raise ValueError('Open-Meteo returned invalid current weather values.') from exc

    description, icon = weather_descriptions.get(weather_code, ('Unknown', '🌡️'))
    return {
        'temperature': temperature,
        'description': description,
        'icon': icon,
        'wind_speed': round(float(current.get('wind_speed_10m') or 0)),
        'updated_at': timezone.now().isoformat(),
    }


@require_GET
def home_weather(request):
    """Return cached Home weather without making the Home document wait.

    One request may refresh an expired cache entry. Concurrent callers receive
    the most recent successful payload (or a neutral unavailable result), which
    prevents a burst of Home visits from issuing duplicate Open-Meteo requests.
    """
    weather = cache.get(HOME_WEATHER_CACHE_KEY)
    if weather:
        return JsonResponse({'weather': weather, 'stale': False})

    last_success = cache.get(HOME_WEATHER_LAST_SUCCESS_CACHE_KEY)
    if not cache.add(
        HOME_WEATHER_REFRESH_LOCK_KEY,
        True,
        timeout=HOME_WEATHER_REFRESH_LOCK_SECONDS,
    ):
        return JsonResponse({'weather': last_success, 'stale': bool(last_success)})

    try:
        weather = _fetch_home_weather()
    except (requests.RequestException, TypeError, ValueError):
        return JsonResponse({'weather': last_success, 'stale': bool(last_success)})

    cache.set(HOME_WEATHER_CACHE_KEY, weather, timeout=HOME_WEATHER_CACHE_SECONDS)
    cache.set(
        HOME_WEATHER_LAST_SUCCESS_CACHE_KEY,
        weather,
        timeout=HOME_WEATHER_LAST_SUCCESS_SECONDS,
    )
    return JsonResponse({'weather': weather, 'stale': False})


def _resolve_home_court_complex(request):
    """
    Resolve which CourtComplex to show on the home page for the current user.

    Priority chain (highest → lowest):
      1. Player's last-used court complex from UserPresencePrefs (billboard history).
      2. Session-stored preferred_court_complex_id (set when user picks a court
         for a friendly game or billboard entry).
      3. None → caller falls back to all-courts aggregate.

    Returns (CourtComplex | None, source_label: str)
    """
    # 1. Billboard prefs (most reliable — updated every time a BillboardEntry is saved)
    codename = request.session.get('player_codename')
    if codename:
        prefs = UserPresencePrefs.get_for_codename(codename)
        if prefs and prefs.last_court_complex_id:
            return prefs.last_court_complex, 'prefs'

    # 2. Session preference (set by friendly game / court selection)
    pref_complex_id = request.session.get(SESSION_PREF_COMPLEX_KEY)
    if pref_complex_id:
        try:
            cc = CourtComplex.objects.get(pk=pref_complex_id)
            return cc, 'session'
        except CourtComplex.DoesNotExist:
            pass

    return None, 'none'


def _get_home_live_scoreboards():
    """Return currently live, read-only scoreboards for the compact home summary.

    The existing LiveScoreboard and underlying Match/FriendlyGame states remain
    authoritative.  This only exposes the same current games already visible on
    the existing live-score list and links to its existing detail view.
    """
    scoreboards = (
        LiveScoreboard.objects.filter(is_active=True)
        .select_related(
            'tournament_match__team1',
            'tournament_match__team2',
            'friendly_game',
        )
        .order_by('-updated_at')
    )
    return [scoreboard for scoreboard in scoreboards if scoreboard.is_match_active()]


def home(request):
    """Render the Welcome Screen using existing profile, presence, and live-score data."""
    # Get team info if a team is logged in.
    team_info = get_team_info_from_session(request)

    # ── At-Courts count ──────────────────────────────────────────────────────
    # Use the canonical get_current_occupancy() from analytics_utils so the
    # home page count is always consistent with the Billboard and Analytics
    # views. The source of truth is BillboardEntry lifecycle (is_active),
    # not a date guard.
    home_court_complex, court_source = _resolve_home_court_complex(request)

    if home_court_complex is not None:
        currently_at_courts = get_current_occupancy(home_court_complex)
        at_courts_court_name = home_court_complex.name
    else:
        # No court context — preserve the existing aggregate fallback.
        all_complexes = CourtComplex.objects.all()
        currently_at_courts = sum(
            get_current_occupancy(cc) for cc in all_complexes
        )
        at_courts_court_name = None

    # ── Existing player profile data ─────────────────────────────────────────
    # Context processors resolve the logged-in Player from the codename session.
    # The separate profile query avoids an exception when legacy players do not
    # yet have an optional PlayerProfile record.
    logged_in_player = None
    home_player_profile = None
    home_player_team = None
    try:
        from pfc_core.session_utils import SessionManager
        logged_in_player = SessionManager.get_session_context(request).get('logged_in_player')
    except (AttributeError, KeyError):
        logged_in_player = None

    if logged_in_player:
        home_player_profile = PlayerProfile.objects.filter(player_id=logged_in_player.pk).first()
        home_player_team = logged_in_player.team

    context = {
        'team_info': team_info,
        'currently_at_courts': currently_at_courts,
        'at_courts_court_name': at_courts_court_name,
        'home_court_complex': home_court_complex,
        'court_source': court_source,
        'home_player_profile': home_player_profile,
        'home_player_team': home_player_team,
        'home_live_scoreboards': _get_home_live_scoreboards(),
    }

    return render(request, 'home.html', context)


@login_required
def dashboard(request):
    """View for the user dashboard"""
    return render(request, 'dashboard.html')


@require_http_methods(["GET"])
def check_team_session(request):
    """
    API endpoint to check the current team session data.
    Used by the frontend to detect team changes and update autofill.

    The ``in_melee_assignment`` flag tells the client whether it should run
    fast 10-second polling (True = player is inside an active Mêlée/Super
    Mêlée dynamic assignment window) or stop recurring polling (False).
    """
    team_pin = request.session.get('team_pin')
    team_name = request.session.get('team_name')
    team_id = request.session.get('team_id')
    is_active = request.session.get('team_session_active', False)
    in_melee_assignment = request.session.get('in_melee_assignment', False)

    return JsonResponse({
        'success': True,
        'data': {
            'is_logged_in': is_active and team_pin is not None,
            'team_pin': team_pin,
            'team_name': team_name,
            'team_id': team_id,
            # True  → client keeps fast 10-second polling active.
            # False → client stops recurring polling (no loop for ordinary users).
            'in_melee_assignment': in_melee_assignment,
        }
    })
