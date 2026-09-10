from pathlib import Path

from django.template.loader import get_template
from django.test import SimpleTestCase


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class PlayerProfilePresentationTests(SimpleTestCase):
    def test_profile_template_compiles_and_keeps_my_practice_self_only(self):
        get_template("teams/player_profile.html")
        source = (PROJECT_ROOT / "teams" / "templates" / "teams" / "player_profile.html").read_text()
        own_profile_start = source.index("{% if is_own_profile %}", source.index("pp-profile-actions"))
        own_profile_end = source.index("{% endif %}", own_profile_start)
        own_profile_actions = source[own_profile_start:own_profile_end]
        self.assertIn("{% url 'practice:practice_home' %}", own_profile_actions)
        self.assertIn("My Practice", own_profile_actions)
        self.assertIn("pp-profile-actions", source)
