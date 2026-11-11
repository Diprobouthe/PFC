from pathlib import Path

from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import resolve, reverse


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class LiveSimpleManagementPersistenceTests(SimpleTestCase):
    def test_live_routes_resolve_to_pfc_core_simple_creator(self):
        self.assertEqual(
            resolve(reverse("simple_creator_home")).func.__module__,
            "pfc_core.simple_creator",
        )
        self.assertEqual(
            resolve(reverse("create_simple_tournament")).func.__module__,
            "pfc_core.simple_creator",
        )
        self.assertEqual(
            resolve(reverse("manage_tournament", kwargs={"tournament_id": 123})).func.__module__,
            "pfc_core.simple_creator",
        )

    def test_live_entry_template_uses_safe_relative_management_destination(self):
        source = (PROJECT_ROOT / "templates" / "simple_creator.html").read_text()
        self.assertIn("pfc.simpleTournamentManagement.v1", source)
        self.assertIn("Continue Tournament Management", source)
        self.assertIn("/^\\/simple\\/manage\\/\\d+\\/(?:[?#].*)?$/", source)
        self.assertIn("continueLink.href = savedManagement.path", source)

    def test_live_management_template_persists_existing_path_and_shows_management_link(self):
        source = (PROJECT_ROOT / "templates" / "simple_tournament_manage.html").read_text()
        self.assertIn("window.location.pathname + window.location.search", source)
        self.assertIn("pfc.simpleTournamentManagement.v1", source)
        self.assertIn("Management Link", source)
        self.assertIn("id=\"management-link\"", source)
        self.assertIn("copyManagementLink", source)
        self.assertNotIn("id=\"registration-link\"", source)

    def test_earlier_success_template_preserves_registration_link(self):
        source = (PROJECT_ROOT / "templates" / "simple_creator_success.html").read_text()
        self.assertIn("Registration Link", source)
        self.assertIn("id=\"registration-link\"", source)
        self.assertIn("{{ registration_url }}", source)
        self.assertNotIn("request.build_absolute_uri", source)


@override_settings(ALLOWED_HOSTS=['www.pfc.events', 'pfc.events', 'testserver', 'localhost'])
class SimpleCreatorRegistrationLinkTests(SimpleTestCase):
    def _success_page(self, mode, tournament_id=200, host='www.pfc.events'):
        from pfc_core.simple_creator import simple_creator_success
        request = RequestFactory().get('/simple/success/', HTTP_HOST=host)
        request.session = {
            'simple_tournament_info': {
                'tournament_id': tournament_id,
                'tournament_name': 'Example Tournament',
                'scenario_mode': mode,
                'registration_link': f'/tournaments/{tournament_id}/',
            },
        }
        return simple_creator_success(request)

    def test_melee_success_link_has_real_registration_route_and_https(self):
        response = self._success_page('melee')
        html = response.content.decode()
        self.assertContains(response, 'https://www.pfc.events/tournaments/200/register/melee/')
        self.assertNotIn('http://www.pfc.events/simple/success/', html)
        self.assertNotIn('/simple/success//tournaments/', html)

    def test_super_melee_uses_same_registration_route(self):
        response = self._success_page('super_melee', 201, 'pfc.events')
        self.assertContains(response, 'https://www.pfc.events/tournaments/201/register/melee/')

    def test_team_tournament_keeps_existing_detail_route(self):
        response = self._success_page('team', 202)
        self.assertContains(response, 'https://www.pfc.events/tournaments/202/')
        self.assertNotContains(response, '/tournaments/202/register/melee/')

    def test_local_dev_keeps_local_origin(self):
        response = self._success_page('melee', 203, 'localhost')
        self.assertContains(response, 'http://localhost/tournaments/203/register/melee/')
