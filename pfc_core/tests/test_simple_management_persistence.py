from pathlib import Path

from django.test import SimpleTestCase
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
        self.assertIn("tournament_info.registration_link", source)
