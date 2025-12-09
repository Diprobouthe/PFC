from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from teams.utils import get_team_info_from_session
from billboard.models import BillboardEntry
from django.utils import timezone
from datetime import timedelta
import requests

def home(request):
    """View for the home page"""
    # Get team info if player is logged in
    team_info = get_team_info_from_session(request)
    
    # Get court occupancy from billboard
    now = timezone.now()
    four_hours_ago = now - timedelta(hours=4)
    
    # Count people currently at courts (last 4 hours)
    # Include both original posters and responders (same logic as billboard)
    at_courts_entries = BillboardEntry.objects.filter(
        action_type='AT_COURTS',
        created_at__gte=four_hours_ago,
        is_active=True
    ).prefetch_related('responses')
    
    currently_at_courts = sum(1 + entry.responses.count() for entry in at_courts_entries)
    
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
        'weather_data': weather_data
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
    """
    team_pin = request.session.get('team_pin')
    team_name = request.session.get('team_name')
    team_id = request.session.get('team_id')
    is_active = request.session.get('team_session_active', False)
    
    return JsonResponse({
        'success': True,
        'data': {
            'is_logged_in': is_active and team_pin is not None,
            'team_pin': team_pin,
            'team_name': team_name,
            'team_id': team_id
        }
    })
