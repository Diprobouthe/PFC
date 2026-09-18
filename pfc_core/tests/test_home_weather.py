from unittest.mock import Mock, patch

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from pfc_core import views


class HomeWeatherTests(TestCase):
    """Home weather is supplementary and must never block document rendering."""

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    @patch('pfc_core.views.requests.get')
    def test_home_renders_without_calling_open_meteo(self, weather_get):
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('weather_data', response.context)
        weather_get.assert_not_called()
        self.assertContains(response, 'id="homeWeather"')

    @patch('pfc_core.views.requests.get')
    def test_weather_endpoint_caches_successful_open_meteo_response(self, weather_get):
        upstream = Mock()
        upstream.raise_for_status.return_value = None
        upstream.json.return_value = {
            'current': {
                'temperature_2m': 24.6,
                'weather_code': 2,
                'wind_speed_10m': 6.2,
            }
        }
        weather_get.return_value = upstream

        first = self.client.get(reverse('home_weather'))
        second = self.client.get(reverse('home_weather'))

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()['weather']['temperature'], 25)
        self.assertFalse(first.json()['stale'])
        self.assertEqual(second.json()['weather'], first.json()['weather'])
        weather_get.assert_called_once()

    @patch('pfc_core.views.requests.get')
    def test_weather_endpoint_returns_last_success_when_refresh_fails(self, weather_get):
        last_success = {
            'temperature': 21,
            'description': 'Clear sky',
            'icon': '☀️',
            'wind_speed': 4,
            'updated_at': '2026-09-18T08:00:00+00:00',
        }
        cache.set(
            views.HOME_WEATHER_LAST_SUCCESS_CACHE_KEY,
            last_success,
            timeout=views.HOME_WEATHER_LAST_SUCCESS_SECONDS,
        )
        weather_get.side_effect = views.requests.RequestException('upstream unavailable')

        response = self.client.get(reverse('home_weather'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['weather'], last_success)
        self.assertTrue(response.json()['stale'])
        weather_get.assert_called_once()

    @patch('pfc_core.views.requests.get')
    def test_weather_refresh_lock_avoids_duplicate_upstream_request(self, weather_get):
        last_success = {
            'temperature': 20,
            'description': 'Overcast',
            'icon': '☁️',
            'wind_speed': 3,
            'updated_at': '2026-09-18T07:00:00+00:00',
        }
        cache.set(
            views.HOME_WEATHER_LAST_SUCCESS_CACHE_KEY,
            last_success,
            timeout=views.HOME_WEATHER_LAST_SUCCESS_SECONDS,
        )
        cache.add(
            views.HOME_WEATHER_REFRESH_LOCK_KEY,
            True,
            timeout=views.HOME_WEATHER_REFRESH_LOCK_SECONDS,
        )

        response = self.client.get(reverse('home_weather'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['weather'], last_success)
        self.assertTrue(response.json()['stale'])
        weather_get.assert_not_called()
