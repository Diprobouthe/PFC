from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from teams.utils import get_team_info_from_session
from billboard.analytics_utils import get_current_occupancy
from billboard.presence_prefs import UserPresencePrefs
from courts.models import CourtComplex
from friendly_games.court_utils import SESSION_PREF_COMPLEX_KEY
from django.utils import timezone
import requests


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


def home(request):
    """View for the home page"""
    # Get team info if player is logged in
    team_info = get_team_info_from_session(request)

    # ── At-Courts count ──────────────────────────────────────────────────────
    # Use the canonical get_current_occupancy() from analytics_utils so the
    # home page count is always consistent with the Billboard and Analytics
    # views.  The source of truth is BillboardEntry lifecycle (is_active),
    # not a date guard.
    #
    # Court complex resolution:
    #   - If the user has a known court context (billboard prefs or session),
    #     show the count for that specific complex.
    #   - Otherwise, show the total across all complexes.
    home_court_complex, court_source = _resolve_home_court_complex(request)

    if home_court_complex is not None:
        # Per-complex count via the canonical helper.
        currently_at_courts = get_current_occupancy(home_court_complex)
        at_courts_court_name = home_court_complex.name
    else:
        # No court context — aggregate across all complexes.
        # Sum per-complex counts (distinct within each complex; a player at
        # multiple complexes simultaneously is counted once per complex, which
        # is the correct physical interpretation).
        all_complexes = CourtComplex.objects.all()
        currently_at_courts = sum(
            get_current_occupancy(cc) for cc in all_complexes
        )
        at_courts_court_name = None  # template shows generic label
    
    # Get weather for Pedion Areos, Athens
    weather_data = None
    try:
        # Using Open-Meteo API (free, no API key required)
        # Pedion Areos coordinates: 37.9908° N, 23.7383° E
        weather_url = 'https://api.open-meteo.com/v1/forecast'
        params = {
            'latitude': 37.9908,
            'longitude': 23.7383,
            'current': 'temperature_2m,weather_code,wind_speed_10m',
            'timezone': 'Europe/Athens'
        }
        response = requests.get(weather_url, params=params, timeout=5)
        if response.status_code == 200:
            data = response.json()
            current = data.get('current', {})
            
            # Map weather codes to descriptions and icons
            weather_code = current.get('weather_code', 0)
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
            
            weather_desc, weather_icon = weather_descriptions.get(weather_code, ('Unknown', '🌡️'))
            
            weather_data = {
                'temperature': round(current.get('temperature_2m', 0)),
                'description': weather_desc,
                'icon': weather_icon,
                'wind_speed': round(current.get('wind_speed_10m', 0))
            }
    except Exception as e:
        # If weather API fails, just don't show weather
        pass
    
    context = {
        'team_info': team_info,
        'currently_at_courts': currently_at_courts,
        'at_courts_court_name': at_courts_court_name,
        'weather_data': weather_data,
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
