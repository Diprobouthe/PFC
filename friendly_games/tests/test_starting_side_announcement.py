from pathlib import Path
from types import SimpleNamespace

from django.template.loader import get_template
from django.test import SimpleTestCase

from pfc_events.push_notifications import _match_body


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class FriendlyStartingSideAnnouncementTests(SimpleTestCase):
    def test_banner_renders_only_for_the_existing_selected_side_until_first_real_score(self):
        template = get_template("partials/friendly_starting_side_announcement.html")
        game = SimpleNamespace(id=41, starting_team="BLACK")
        visible = template.render(
            {
                "friendly_game": game,
                "starting_side_is_recipient": True,
                "starting_side_has_score": False,
                "starting_side_scoreboard_id": 77,
                "listen_for_score_updates": False,
            }
        )
        self.assertIn("Black Team", visible)
        self.assertIn("starts first", visible)
        self.assertNotIn("localStorage", visible)
        self.assertNotIn("Dismiss", visible)

        other_side = template.render(
            {
                "friendly_game": game,
                "starting_side_is_recipient": False,
                "starting_side_has_score": False,
                "starting_side_scoreboard_id": 77,
                "listen_for_score_updates": False,
            }
        )
        self.assertNotIn('id="friendly-starting-side-banner"', other_side)

        after_score = template.render(
            {
                "friendly_game": game,
                "starting_side_is_recipient": True,
                "starting_side_has_score": True,
                "starting_side_scoreboard_id": 77,
                "listen_for_score_updates": False,
            }
        )
        self.assertNotIn('id="friendly-starting-side-banner"', after_score)

    def test_scoreboard_template_removes_banner_only_for_a_real_score_update(self):
        source = (
            PROJECT_ROOT / "templates" / "matches" / "scoreboard_detail.html"
        ).read_text()
        self.assertIn("friendly_starting_side_announcement.html", source)
        self.assertIn("hideForFirstScore(data)", source)
        self.assertIn("Number(scoreUpdate.team1_score) > 0", (
            PROJECT_ROOT / "templates" / "partials" / "friendly_starting_side_announcement.html"
        ).read_text())

    def test_friendly_start_push_wording_and_recipients_remain_selected_side_only(self):
        body = _match_body("friendly_starts", "en")
        self.assertIn("Your side was selected to start the Friendly Game", body)
        source = (PROJECT_ROOT / "friendly_games" / "views.py").read_text()
        self.assertIn("starting_side_players = list(game.players.filter(team=game.starting_team)", source)
        self.assertIn("notify_match_action_required(starting_side_players, 'friendly_starts'", source)
