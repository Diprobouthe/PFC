from pathlib import Path

from django.conf import settings
from django.template.loader import get_template
from django.test import SimpleTestCase


class LineupAutoTransitionTemplateTests(SimpleTestCase):
    def test_templates_compile(self):
        get_template("matches/match_activate.html")
        get_template("matches/match_detail.html")

    def test_lineup_form_listens_for_server_state_change_and_has_fallback(self):
        source = (
            Path(settings.BASE_DIR) / "templates" / "matches" / "match_activate.html"
        ).read_text(encoding="utf-8")
        self.assertIn("/ws/match/{{ match.id }}/", source)
        self.assertIn("data.type !== 'match.state_changed'", source)
        self.assertIn("data.next_url || data.state_url || lineupStateUrl", source)
        self.assertIn("lineupFallbackTimer", source)

    def test_pending_match_detail_keeps_state_socket_open(self):
        source = (
            Path(settings.BASE_DIR) / "templates" / "matches" / "match_detail.html"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "match.status == 'pending' or match.status == 'active'",
            source,
        )
