"""Team scenarios and VS Mode regression tests.

Only Django's disposable test DB is used. No production credentials, deployed
data, model migrations, or operational app logic are changed by this suite.
Run: python manage.py test tournaments.test_team_vs_scenarios_regression -v 2

A failing assertion signals an unresolved regression. Do not xfail it to
manufacture a green build.
"""
import json
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from courts.models import Court, CourtComplex
from matches.models import Match
from signin.services import activate_team_tournament_signin
from simple_creator.models import ScenarioStage, TournamentScenario
from teams.models import Player, Team
from tournaments.models import Tournament, TournamentTeam, VSEncounter
from tournaments.registration_services import register_team_for_tournament
from tournaments.vs_utils import update_vs_encounter_points
from leaderboards.models import Leaderboard


class TeamScenarioRegressionTests(TestCase):
    def setUp(self):
        self.complex = CourtComplex.objects.create(
            name="Team regression complex", description="Isolated test complex"
        )
        courts = [
            Court.objects.create(number=88101 + n, is_available=True)
            for n in range(3)
        ]
        self.complex.courts.add(*courts)

    def scenario(self, key, algorithm="swiss", per_team=3):
        return TournamentScenario.objects.create(
            name=f"reg-team-{key}", display_name=f"Regression {key}",
            description="Automated team regression",
            default_court_complex=self.complex,
            scenario_mode="team", tournament_type=algorithm,
            num_rounds=3, matches_per_team=per_team, draft_type="random",
            is_free=True, requires_voucher=False, max_courts=3,
            recommended_courts=2, lineup_selection_seconds=60,
        )

    def create_via_active_ui(self, scenario):
        response = self.client.post(reverse("create_simple_tournament"), {
            "scenario": scenario.name, "format": "doubles", "num_courts": "2",
        })
        self.assertEqual(response.status_code, 302)
        tournament = Tournament.objects.filter(
            name__startswith=scenario.display_name
        ).order_by("-pk").first()
        self.assertIsNotNone(tournament, "Active /simple/create/ did not create a tournament")
        return tournament

    def add_teams(self, tournament, count, prefix):
        teams = []
        for n in range(count):
            team = Team.objects.create(
                name=f"{prefix} {n}",
                pin=f"{880100 + Team.objects.count():06d}",
            )
            for p in range(2):
                Player.objects.create(name=f"{prefix} {n} player {p}", team=team)
            TournamentTeam.objects.create(
                tournament=tournament, team=team, is_active=True
            )
            teams.append(team)
        return teams

    def assert_unique_pairings(self, matches, teams, expected):
        self.assertEqual(len(matches), expected)
        participants = [
            team_id for match in matches
            for team_id in (match.team1_id, match.team2_id)
        ]
        self.assertEqual(len(participants), len(set(participants)))
        self.assertTrue(set(participants).issubset({team.id for team in teams}))

    def test_live_team_creator_preserves_team_mode_and_courts(self):
        tournament = self.create_via_active_ui(self.scenario("basic"))
        self.assertFalse(tournament.is_melee)
        self.assertTrue(tournament.is_multi_stage)
        self.assertEqual(tournament.format, "multi_stage")
        self.assertEqual(tournament.courts.count(), 2)
        self.assertEqual(tournament.stages.count(), 1)

    def test_configured_two_stage_team_scenario_copies_both_stages(self):
        """Known risk: live creator must not replace 2 configured stages with 1."""
        scenario = self.scenario("groups-final", algorithm="round_robin")
        ScenarioStage.objects.create(
            scenario=scenario, stage_number=1, name="Groups",
            format="round_robin", num_qualifiers=4, num_rounds_in_stage=3,
        )
        ScenarioStage.objects.create(
            scenario=scenario, stage_number=2, name="Finals",
            format="knockout", num_qualifiers=0, num_rounds_in_stage=2,
        )
        tournament = self.create_via_active_ui(scenario)
        self.assertEqual(
            list(tournament.stages.order_by("stage_number").values_list(
                "stage_number", "name", "format", "num_qualifiers"
            )),
            [(1, "Groups", "round_robin", 4), (2, "Finals", "knockout", 0)],
        )

    def test_explicit_team_stage_settings_are_copied_without_mutating_templates(self):
        scenario = self.scenario("settings", algorithm="round_robin")
        first = ScenarioStage.objects.create(
            scenario=scenario, stage_number=1, name="Qualifiers",
            format="round_robin", num_qualifiers=2, num_rounds_in_stage=3,
            num_matches_per_team=2,
        )
        second = ScenarioStage.objects.create(
            scenario=scenario, stage_number=2, name="Final",
            format="knockout", num_qualifiers=0, num_rounds_in_stage=1,
        )
        tournament = self.create_via_active_ui(scenario)
        stages = list(tournament.stages.order_by("stage_number"))
        self.assertEqual(len(stages), 2)
        self.assertEqual(stages[0].num_qualifiers, 2)
        self.assertEqual(stages[0].num_rounds_in_stage, 3)
        self.assertEqual(stages[0].num_matches_per_team, 2)
        self.assertEqual(stages[1].num_rounds_in_stage, 1)
        self.assertIsNone(stages[1].num_matches_per_team)
        self.assertEqual((first.num_qualifiers, second.num_qualifiers), (2, 0))

    def test_melee_variants_ignore_team_stage_templates(self):
        for mode in ("melee", "super_melee"):
            with self.subTest(mode=mode):
                scenario = self.scenario(f"isolated-{mode}")
                scenario.scenario_mode = mode
                scenario.save(update_fields=["scenario_mode"])
                ScenarioStage.objects.create(
                    scenario=scenario, stage_number=1, name="Unexpected group",
                    format="round_robin", num_qualifiers=2, num_rounds_in_stage=2,
                )
                ScenarioStage.objects.create(
                    scenario=scenario, stage_number=2, name="Unexpected final",
                    format="knockout", num_qualifiers=0, num_rounds_in_stage=1,
                )
                tournament = self.create_via_active_ui(scenario)
                self.assertTrue(tournament.is_melee)
                self.assertEqual(
                    tournament.shuffle_players_after_round,
                    mode == "super_melee",
                )
                self.assertEqual(
                    list(tournament.stages.values_list("name", "format")),
                    [("Main Stage", "swiss")],
                    "Existing P4 scenario creation must remain unchanged",
                )

    def test_swiss_first_round_with_four_six_eight_teams(self):
        for count in (4, 6, 8):
            with self.subTest(teams=count):
                tournament = self.create_via_active_ui(
                    self.scenario(f"swiss-{count}")
                )
                teams = self.add_teams(tournament, count, f"Swiss {count}")
                self.assertEqual(tournament.generate_matches(), count // 2)
                matches = list(Match.objects.filter(tournament=tournament))
                self.assert_unique_pairings(matches, teams, count // 2)
                self.assertTrue(all(m.round_id for m in matches))

    def test_round_robin_odd_even_first_round_and_bye(self):
        for count in (5, 6):
            with self.subTest(teams=count):
                tournament = self.create_via_active_ui(
                    self.scenario(
                        f"rr-{count}", algorithm="round_robin", per_team=count - 1
                    )
                )
                teams = self.add_teams(tournament, count, f"RR {count}")
                self.assertEqual(tournament.generate_matches(), count // 2)
                matches = list(Match.objects.filter(tournament=tournament))
                self.assert_unique_pairings(matches, teams, count // 2)
                self.assertEqual(count - len(matches) * 2, count % 2)

    def test_team_start_endpoint_is_idempotent(self):
        tournament = self.create_via_active_ui(self.scenario("start"))
        self.add_teams(tournament, 4, "Start")
        url = reverse("start_tournament", args=[tournament.pk])
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(Match.objects.filter(tournament=tournament).count(), 2)
        self.assertEqual(self.client.post(url).status_code, 302)
        self.assertEqual(Match.objects.filter(tournament=tournament).count(), 2)


class VSModeRegressionTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.tournament = Tournament.objects.create(
            name="VS regression",
            format="independent_games", play_format="mixed",
            has_tete_a_tete=True, has_doublets=True, has_triplets=True,
            allowed_match_types={
                "vs_mode": True, "vs_num_matches": 3,
                "allowed_match_types": ["tete_a_tete", "doublet", "triplet"],
                "allow_mixed": False,
            },
            is_melee=False, max_participants=2,
            start_date=now + timedelta(days=1),
            end_date=now + timedelta(days=2),
        )
        self.tournament.courts.add(
            *[Court.objects.create(number=88501 + n) for n in range(3)]
        )
        self.teams = [
            Team.objects.create(name=f"VS Test {n}", pin=f"88100{n}")
            for n in range(3)
        ]
        self.players = {
            team.pk: [
                Player.objects.create(name=f"{team.name} player {n}", team=team)
                for n in range(3)
            ] for team in self.teams
        }

    def register_two(self):
        activate_team_tournament_signin(
            team=self.teams[0], tournament=self.tournament
        )
        activate_team_tournament_signin(
            team=self.teams[1], tournament=self.tournament
        )
        return VSEncounter.objects.get(tournament=self.tournament)

    def use_vs_compat_pin(self, team):
        # Deliberately exercises lineups independently of the normal-login
        # regression below. This is *not* how a real user logs in.
        session = self.client.session
        session[f"team_pin_{self.tournament.pk}"] = team.pin
        session.save()

    def post_lineup(self, match, team, count):
        self.use_vs_compat_pin(team)
        return self.client.post(
            reverse("vs_lineup_submit", args=[match.pk]),
            data=json.dumps({
                "player_ids": [p.pk for p in self.players[team.pk][:count]]
            }),
            content_type="application/json",
        )

    def test_exactly_two_signins_create_one_encounter_and_open_matches(self):
        activate_team_tournament_signin(
            team=self.teams[0], tournament=self.tournament
        )
        self.assertFalse(VSEncounter.objects.filter(tournament=self.tournament).exists())
        self.assertFalse(Match.objects.filter(tournament=self.tournament).exists())
        self.register_two()
        matches = list(Match.objects.filter(tournament=self.tournament))
        self.assertEqual(VSEncounter.objects.filter(tournament=self.tournament).count(), 1)
        self.assertEqual(len(matches), 3)
        self.assertTrue(all(
            m.status == "pending" and m.match_type is None
            and m.vs_points_value is None for m in matches
        ))

    def test_repeat_signin_does_not_duplicate_encounter_or_matches(self):
        self.register_two()
        self.register_two()
        self.assertEqual(VSEncounter.objects.filter(tournament=self.tournament).count(), 1)
        self.assertEqual(Match.objects.filter(tournament=self.tournament).count(), 3)
        self.assertEqual(TournamentTeam.objects.filter(tournament=self.tournament).count(), 2)

    def test_third_team_rejected_on_standard_vs_signin(self):
        self.register_two()
        with self.assertRaises(ValidationError):
            activate_team_tournament_signin(
                team=self.teams[2], tournament=self.tournament
            )
        self.assertEqual(TournamentTeam.objects.filter(tournament=self.tournament).count(), 2)

    def test_generic_registration_must_not_bypass_vs_team_limit(self):
        """Known risk: an alternative registration route bypasses VS invariants."""
        self.register_two()
        with self.assertRaises(ValidationError):
            register_team_for_tournament(
                team=self.teams[2], tournament=self.tournament
            )
        self.assertEqual(TournamentTeam.objects.filter(tournament=self.tournament).count(), 2)

    def test_vs_logged_in_player_uses_original_activation_form_and_positions(self):
        """Google/email player session must open the existing full Match UI."""
        from friendly_games.models import PlayerCodename
        from pfc_core.smart_router import _resolve_tournament_matches

        encounter = self.register_two()
        match = Match.objects.filter(vs_encounter=encounter).order_by("pk").first()
        player = self.players[self.teams[0].pk][0]
        PlayerCodename.objects.create(player=player, codename="VSX001")
        session = self.client.session
        session["player_codename"] = "VSX001"
        session["session_active"] = True
        session.save()

        old_url = reverse("vs_sub_game_detail", args=[match.pk])
        details_url = reverse("match_detail", args=[match.pk])
        activation_url = reverse(
            "match_activate", args=[match.pk, self.teams[0].pk]
        )
        self.assertRedirects(self.client.get(old_url), details_url)
        overview = self.client.get(reverse("vs_encounter_detail", args=[encounter.pk]))
        self.assertContains(overview, details_url)
        self.assertNotContains(overview, old_url)

        choices = _resolve_tournament_matches(player)
        self.assertTrue(any(action["url"] == activation_url for action in choices))
        self.assertFalse(any("/vs/sub-game/" in action["url"] for action in choices))
        details = self.client.get(details_url)
        self.assertEqual(details.context["my_team"], self.teams[0])
        response = self.client.get(activation_url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "matches/match_activate.html")
        self.assertContains(response, "role_")
        self.assertContains(response, "Pointer")
        self.assertContains(response, "Milieu")
        self.assertContains(response, "Shooter")
        for teammate in self.players[self.teams[0].pk]:
            self.assertContains(response, teammate.name)

    def test_canonical_two_team_vs_activation_keeps_roles_court_and_clock(self):
        """Two existing MatchActivationForm POSTs own all VS activation state."""
        from django.test import Client
        from matches.models import MatchActivation, MatchPlayer
        from tournaments.models import VSLineup

        encounter = self.register_two()
        match = Match.objects.filter(vs_encounter=encounter).order_by("pk").first()
        clients = [self.client, Client()]
        role_choices = ("pointer", "milieu", "tirer")
        for team, client in zip(self.teams[:2], clients):
            login = client.post(
                reverse("team_pin_login"),
                data=json.dumps({"team_pin": team.pin, "remember_me": False}),
                content_type="application/json",
            )
            self.assertEqual(login.status_code, 200)
            self.assertTrue(login.json()["success"])
            player_ids = [p.pk for p in self.players[team.pk]]
            data = {"pin": team.pin, "players": player_ids}
            data.update({
                f"role_{player_id}": role_choices[index]
                for index, player_id in enumerate(player_ids)
            })
            url = reverse("match_activate", args=[match.pk, team.pk])
            page = client.get(url)
            self.assertEqual(page.status_code, 200)
            self.assertTemplateUsed(page, "matches/match_activate.html")
            with self.captureOnCommitCallbacks(execute=True):
                submitted = client.post(url, data)
            self.assertEqual(submitted.status_code, 302, submitted.content)

        match.refresh_from_db()
        self.assertEqual(match.status, "active")
        self.assertIsNotNone(match.court_id)
        self.assertIsNotNone(match.start_time)
        self.assertEqual(match.match_type, "triplet")
        self.assertEqual(match.vs_points_value, 5)
        self.assertEqual(MatchActivation.objects.filter(match=match).count(), 2)
        self.assertFalse(VSLineup.objects.filter(match=match).exists())
        self.assertEqual(MatchPlayer.objects.filter(match=match).count(), 6)
        for team in self.teams[:2]:
            actual = list(MatchPlayer.objects.filter(match=match, team=team)
                          .order_by("player_id").values_list("role", flat=True))
            self.assertEqual(sorted(actual), sorted(role_choices))
        self.assertIsNotNone(match.starting_team_id)

    def test_provisional_vslineup_does_not_override_real_match_roster_in_pdf(self):
        """A partially locked historical VS draft must not corrupt the final sheet."""
        from matches.models import MatchPlayer
        from tournaments.models import VSLineup
        from tournaments.pdf_reports import _player_names

        encounter = self.register_two()
        match = Match.objects.filter(vs_encounter=encounter).first()
        provisional = VSLineup.objects.create(
            match=match, team=self.teams[0], is_locked=True,
        )
        provisional.players.add(self.players[self.teams[0].pk][0])
        Match.objects.filter(pk=match.pk).update(
            vs_lineup_team1_locked=True, status="completed",
        )
        actual = self.players[self.teams[0].pk][1]
        MatchPlayer.objects.create(
            match=match, player=actual, team=self.teams[0], role="tirer",
            match_format="tete_a_tete",
        )
        match.refresh_from_db()
        match = Match.objects.prefetch_related(
            "vs_lineups__players", "match_players__player"
        ).get(pk=match.pk)
        roster = _player_names(match, self.teams[0].pk)
        self.assertEqual(roster, actual.name)
        self.assertNotIn(self.players[self.teams[0].pk][0].name, roster)

    def test_normal_team_login_must_authorize_vs_lineup(self):
        """Known risk: normal login stores 'team_pin', VS reads 'team_pin_<id>'."""
        self.register_two()
        response = self.client.post(
            reverse("team_pin_login"),
            data=json.dumps({
                "team_pin": self.teams[0].pin, "remember_me": False,
            }), content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(self.client.session.get("team_pin"), self.teams[0].pin)
        match = Match.objects.filter(tournament=self.tournament).first()
        response = self.client.get(reverse("vs_lineup_submit", args=[match.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_unregistered_third_team_cannot_submit_vs_lineup(self):
        self.register_two()
        match = Match.objects.filter(tournament=self.tournament).first()
        response = self.post_lineup(match, self.teams[2], 1)
        self.assertEqual(response.status_code, 403)

    def test_mismatched_lineups_rejected_before_second_lock(self):
        self.register_two()
        match = Match.objects.filter(tournament=self.tournament).first()
        first = self.post_lineup(match, self.teams[0], 1)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["opponent_players"], [])
        other = self.post_lineup(match, self.teams[1], 2)
        self.assertEqual(other.status_code, 400)
        match.refresh_from_db()
        self.assertFalse(match.vs_lineup_team2_locked)
        self.assertEqual(match.status, "pending")

    def test_opponent_players_hidden_until_both_lock(self):
        self.register_two()
        match = Match.objects.filter(tournament=self.tournament).first()
        self.assertEqual(self.post_lineup(match, self.teams[0], 1).status_code, 200)
        self.use_vs_compat_pin(self.teams[1])
        response = self.client.get(reverse("vs_lineup_submit", args=[match.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["opponent_players"], [])
        self.assertTrue(response.json()["opponent_lineup_locked"])

    def test_equal_lineups_determine_format_and_two_three_five_points(self):
        self.register_two()
        matches = list(Match.objects.filter(tournament=self.tournament).order_by("pk"))
        for match, count, fmt, pts in zip(
            matches, (1, 2, 3), ("tete_a_tete", "doublet", "triplet"), (2, 3, 5)
        ):
            with self.subTest(players_per_side=count):
                self.assertEqual(
                    self.post_lineup(match, self.teams[0], count).status_code, 200
                )
                response = self.post_lineup(match, self.teams[1], count)
                self.assertEqual(response.status_code, 200, response.content)
                match.refresh_from_db()
                self.assertEqual(match.match_type, fmt)
                self.assertEqual(match.vs_points_value, pts)
                self.assertEqual(match.team1_player_count, count)
                self.assertEqual(match.team2_player_count, count)

    def test_real_team_pin_vs_single_match_score_and_points(self):
        """Real login -> lineup locks -> Court -> score -> opponent validation."""
        encounter = self.register_two()
        match = Match.objects.filter(vs_encounter=encounter).order_by("pk").first()

        for team in self.teams[:2]:
            login = self.client.post(
                reverse("team_pin_login"),
                data=json.dumps({"team_pin": team.pin, "remember_me": False}),
                content_type="application/json",
            )
            self.assertEqual(login.status_code, 200)
            self.assertTrue(login.json()["success"])
            selected_player = self.players[team.pk][0]
            response = self.client.post(
                reverse("vs_lineup_submit", args=[match.pk]),
                data=json.dumps({"player_ids": [selected_player.pk]}),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200, response.content)

        match.refresh_from_db()
        self.assertEqual(match.status, "active")
        self.assertIsNotNone(match.court_id)
        self.assertEqual(match.vs_points_value, 2)

        login = self.client.post(
            reverse("team_pin_login"),
            data=json.dumps({
                "team_pin": self.teams[0].pin, "remember_me": False,
            }), content_type="application/json",
        )
        self.assertTrue(login.json()["success"])
        submitted = self.client.post(
            reverse("match_submit_result", kwargs={
                "match_id": match.pk, "team_id": self.teams[0].pk,
            }),
            {"team1_score": 13, "team2_score": 7},
        )
        self.assertEqual(submitted.status_code, 302)
        match.refresh_from_db()
        self.assertEqual(match.status, "waiting_validation")

        login = self.client.post(
            reverse("team_pin_login"),
            data=json.dumps({
                "team_pin": self.teams[1].pin, "remember_me": False,
            }), content_type="application/json",
        )
        self.assertTrue(login.json()["success"])
        with self.captureOnCommitCallbacks(execute=True):
            validated = self.client.post(
                reverse("match_validate_result", kwargs={
                    "match_id": match.pk, "team_id": self.teams[1].pk,
                }),
                {"validation_action": "agree"},
            )
        self.assertEqual(validated.status_code, 302)
        match.refresh_from_db()
        self.assertEqual(match.status, "completed")
        self.assertEqual(match.winner_id, self.teams[0].pk)
        encounter.refresh_from_db()
        self.assertEqual(
            (encounter.team1_points, encounter.team2_points), (2, 0)
        )
        self.assertTrue(Leaderboard.objects.filter(tournament=self.tournament).exists())
        response = self.client.get(
            reverse("tournament_leaderboard", args=[self.tournament.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["entries"][0].swiss_points, 2)

    def test_current_team_pin_precedes_legacy_scoped_vs_pin(self):
        """A stale VS compatibility key must not override a new Team login."""
        self.register_two()
        match = Match.objects.filter(tournament=self.tournament).first()
        self.use_vs_compat_pin(self.teams[0])
        login = self.client.post(
            reverse("team_pin_login"),
            data=json.dumps({
                "team_pin": self.teams[1].pin, "remember_me": False,
            }), content_type="application/json",
        )
        self.assertTrue(login.json()["success"])
        response = self.client.get(reverse("vs_lineup_submit", args=[match.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertFalse(response.json()["own_lineup_locked"])

    def test_legacy_vs_leaderboard_is_read_only_without_recreating_tournament(self):
        encounter = self.register_two()
        match = Match.objects.filter(vs_encounter=encounter).order_by("pk").first()
        Match.objects.filter(pk=match.pk).update(
            status="completed", winner=self.teams[0],
            match_type="doublet", vs_points_value=3,
            team1_score=13, team2_score=9,
        )
        self.assertFalse(Leaderboard.objects.filter(tournament=self.tournament).exists())
        response = self.client.get(
            reverse("tournament_leaderboard", args=[self.tournament.pk])
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [(row.team_id, row.swiss_points) for row in response.context["entries"]],
            [(self.teams[0].pk, 3), (self.teams[1].pk, 0)],
        )
        self.assertFalse(Leaderboard.objects.filter(tournament=self.tournament).exists())

    def test_vs_match_activate_is_not_redirected_to_parallel_lineup(self):
        self.register_two()
        match = Match.objects.filter(tournament=self.tournament).first()
        page = self.client.get(reverse(
            "match_activate", args=[match.pk, self.teams[0].pk]
        ))
        self.assertEqual(page.status_code, 200)
        self.assertTemplateUsed(page, "matches/match_activate.html")
        self.assertNotContains(page, "Lock Lineup")

    def test_recalculating_vs_points_is_idempotent(self):
        encounter = self.register_two()
        matches = list(Match.objects.filter(vs_encounter=encounter).order_by("pk"))
        for match, winner, points in zip(
            matches, (self.teams[0], self.teams[1], self.teams[0]), (2, 3, 5)
        ):
            # Queryset.update intentionally avoids lifecycle/signal side effects:
            # this test only verifies the VS score projection in isolation.
            Match.objects.filter(pk=match.pk).update(
                status="completed", winner=winner, vs_points_value=points
            )
        update_vs_encounter_points(encounter)
        update_vs_encounter_points(encounter)
        encounter.refresh_from_db()
        self.assertTrue(encounter.is_complete)
        self.assertEqual((encounter.team1_points, encounter.team2_points), (7, 3))
        points_by_team = {
            row.team_id: row.vs_points
            for row in TournamentTeam.objects.filter(tournament=self.tournament)
        }
        self.assertEqual(points_by_team[self.teams[0].pk], 7)
        self.assertEqual(points_by_team[self.teams[1].pk], 3)


class TeamTournamentEndToEndBaselineTests(TestCase):
    """Baseline: real UI -> team signins -> 3 played Rounds -> final publication.

    Uses Django's disposable PostgreSQL test database; never production data.
    Official result services are exercised, and the pending post-commit
    lifecycle dispatcher is explicitly drained because TestCase wraps the
    whole method in a rollback-only test transaction.
    """

    def setUp(self):
        from courts.models import Court, CourtComplex
        self.complex = CourtComplex.objects.create(
            name="E2E team baseline courts", description="Disposable test"
        )
        courts = [Court.objects.create(number=88901 + n, is_available=True)
                  for n in range(2)]
        self.complex.courts.add(*courts)
        self.teams = []
        for n in range(4):
            team = Team.objects.create(name=f"E2E Team {n}", pin=f"88900{n}")
            for p in range(2):
                Player.objects.create(name=f"E2E Player {n}-{p}", team=team)
            self.teams.append(team)

    def _create_and_signin(self, algorithm):
        scenario = TournamentScenario.objects.create(
            name=f"e2e-{algorithm}",
            display_name=f"E2E {algorithm}",
            description="Three-round team baseline",
            default_court_complex=self.complex,
            scenario_mode="team", tournament_type=algorithm,
            num_rounds=3, matches_per_team=3,
            draft_type="random", is_free=True, requires_voucher=False,
            max_courts=2, recommended_courts=2,
            lineup_selection_seconds=0,
        )
        response = self.client.post(reverse("create_simple_tournament"), {
            "scenario": scenario.name, "format": "doubles", "num_courts": "2",
        })
        self.assertEqual(response.status_code, 302)
        tournament = Tournament.objects.filter(
            name__startswith=scenario.display_name
        ).order_by("-pk").first()
        self.assertIsNotNone(tournament, "Simple Creator returned no tournament")
        self.assertFalse(tournament.is_melee)
        self.assertEqual(tournament.stages.count(), 1)
        for team in self.teams:
            signin = activate_team_tournament_signin(
                team=team, tournament=tournament
            )
            self.assertIsNotNone(signin["tournament_team"])
        self.assertEqual(
            TournamentTeam.objects.filter(tournament=tournament, is_active=True).count(), 4
        )
        return tournament

    def _run_all_three_rounds(self, algorithm):
        from matches.lifecycle import (
            submit_official_result, validate_official_result,
            process_tournament_transition,
        )
        from matches.models import MatchPlayer
        from tournaments.lineup_lifecycle import finalize_round_lineups
        from tournaments.models import Round, RoundLifecycleTransition
        from leaderboards.models import Leaderboard, LeaderboardEntry

        tournament = self._create_and_signin(algorithm)
        start = self.client.post(reverse("start_tournament", args=[tournament.id]))
        self.assertEqual(start.status_code, 302)
        all_pairs = []
        for round_number in (1, 2, 3):
            round_obj = Round.objects.filter(
                tournament=tournament, number_in_stage=round_number
            ).order_by("id").first()
            self.assertIsNotNone(
                round_obj, f"{algorithm}: Round {round_number} not generated"
            )
            matches = list(Match.objects.filter(round=round_obj).order_by("id"))
            self.assertEqual(
                len(matches), 2, f"{algorithm}: Round {round_number} match count"
            )
            for match in matches:
                self.assertNotEqual(match.team1_id, match.team2_id)
                all_pairs.append(frozenset((match.team1_id, match.team2_id)))
            outcome = finalize_round_lineups(round_obj.id)
            self.assertTrue(
                outcome.frozen,
                f"{algorithm}: Round {round_number} lineups blocked {outcome.blocked_match_ids}"
            )
            self.assertEqual(
                len(outcome.ready_match_ids), 2,
                f"{algorithm}: Round {round_number} eligible matches"
            )
            for match in matches:
                match.refresh_from_db()
                self.assertEqual(
                    MatchPlayer.objects.filter(match=match).count(), 4,
                    f"{algorithm}: match {match.pk} missing saved player lineup"
                )
                self.assertEqual(
                    match.status, "active",
                    f"{algorithm}: Round {round_number} match {match.id} not on Court"
                )
                self.assertIsNotNone(match.court_id)
                submitted = submit_official_result(
                    match.id, submitted_by_id=match.team1_id,
                    team1_score=13, team2_score=7,
                )
                self.assertEqual(submitted.state, "submitted")
                validated = validate_official_result(
                    match.id, validating_team_id=match.team2_id, agree=True,
                )
                self.assertEqual(validated.state, "completed")
                self.assertTrue(
                    process_tournament_transition(match.id),
                    f"{algorithm}: match {match.id} post-result transition failed"
                )
            round_obj.refresh_from_db()
            transition = RoundLifecycleTransition.objects.filter(round=round_obj).first()
            self.assertIsNotNone(
                transition, f"{algorithm}: Round {round_number} never triggered lifecycle"
            )
            self.assertEqual(
                transition.status, RoundLifecycleTransition.COMPLETED,
                f"{algorithm}: Round {round_number} transition failed: {transition.last_error}"
            )
            print(
                f"TEAM_BASELINE {algorithm} round={round_number} "
                f"completed={Match.objects.filter(round=round_obj, status='completed').count()} "
                f"next_round={Round.objects.filter(tournament=tournament).count()}",
                flush=True,
            )

        self.assertEqual(Match.objects.filter(tournament=tournament).count(), 6)
        self.assertEqual(len(all_pairs), 6)
        if algorithm == "round_robin":
            self.assertEqual(len(set(all_pairs)), 6, "Round Robin repeated opponents")

        tournament.refresh_from_db()
        self.assertEqual(
            tournament.automation_status, "completed",
            f"{algorithm}: three rounds played but tournament not finalized"
        )
        self.assertTrue(tournament.is_archived)
        self.assertFalse(tournament.is_active)
        self.assertEqual(
            LeaderboardEntry.objects.filter(leaderboard__tournament=tournament).count(), 4,
            f"{algorithm}: final standings did not contain four Teams"
        )
        self.assertEqual(
            sorted(
                LeaderboardEntry.objects.filter(
                    leaderboard__tournament=tournament
                ).values_list("position", flat=True)
            ), [1, 2, 3, 4],
        )
        for team in self.teams:
            self.assertEqual(
                Player.objects.filter(team=team).count(), 2,
                f"{algorithm}: regular Player.team affiliation changed"
            )
        print(f"TEAM_BASELINE {algorithm} FINALIZED OK", flush=True)

    def test_three_round_swiss_from_ui_to_final_leaderboard(self):
        self._run_all_three_rounds("swiss")

    def test_three_round_round_robin_from_ui_to_final_leaderboard(self):
        self._run_all_three_rounds("round_robin")


    def test_round_robin_groups_to_two_round_knockout_final(self):
        """Configured Team Stage handoff must work through the actual match lifecycle."""
        from matches.lifecycle import (
            submit_official_result, validate_official_result,
            process_tournament_transition,
        )
        from tournaments.lineup_lifecycle import finalize_round_lineups
        from tournaments.models import Round, RoundLifecycleTransition
        from leaderboards.models import LeaderboardEntry

        scenario = TournamentScenario.objects.create(
            name="e2e-groups-final",
            display_name="E2E Groups Final",
            description="Round Robin qualifier then knockout",
            default_court_complex=self.complex,
            scenario_mode="team", tournament_type="round_robin",
            num_rounds=3, matches_per_team=3,
            draft_type="random", is_free=True, requires_voucher=False,
            max_courts=2, recommended_courts=2,
            lineup_selection_seconds=0,
        )
        ScenarioStage.objects.create(
            scenario=scenario, stage_number=1, name="Groups",
            format="round_robin", num_qualifiers=4, num_rounds_in_stage=3,
        )
        ScenarioStage.objects.create(
            scenario=scenario, stage_number=2, name="Final",
            format="knockout", num_qualifiers=0, num_rounds_in_stage=2,
        )
        response = self.client.post(reverse("create_simple_tournament"), {
            "scenario": scenario.name, "format": "doubles", "num_courts": "2",
        })
        self.assertEqual(response.status_code, 302)
        tournament = Tournament.objects.filter(
            name__startswith=scenario.display_name
        ).order_by("-id").first()
        self.assertIsNotNone(tournament)
        groups, final = list(tournament.stages.order_by("stage_number"))
        self.assertEqual((groups.name, groups.format), ("Groups", "round_robin"))
        self.assertEqual((final.name, final.format), ("Final", "knockout"))
        for team in self.teams:
            activate_team_tournament_signin(team=team, tournament=tournament)
        self.assertEqual(
            self.client.post(reverse("start_tournament", args=[tournament.id])).status_code,
            302,
        )
        for stage, stage_round_num, expected_matches in (
            (groups, 1, 2), (groups, 2, 2), (groups, 3, 2),
            (final, 1, 2), (final, 2, 1),
        ):
            round_obj = Round.objects.filter(
                tournament=tournament,
                stage=stage,
                number_in_stage=stage_round_num,
            ).first()
            self.assertIsNotNone(
                round_obj,
                f"No round {stage_round_num} in {stage.name}; "
                "Team Stage progression did not produce the expected matches",
            )
            matches = list(Match.objects.filter(round=round_obj).order_by("id"))
            self.assertEqual(len(matches), expected_matches)
            outcome = finalize_round_lineups(round_obj.id)
            self.assertTrue(outcome.frozen, f"Lineup blocked: {outcome.blocked_match_ids}")
            self.assertEqual(len(outcome.ready_match_ids), expected_matches)
            for match in matches:
                match.refresh_from_db()
                self.assertEqual(match.status, "active")
                self.assertIsNotNone(match.court_id)
                self.assertEqual(
                    submit_official_result(
                        match.id, submitted_by_id=match.team1_id,
                        team1_score=13, team2_score=7,
                    ).state, "submitted",
                )
                self.assertEqual(
                    validate_official_result(
                        match.id, validating_team_id=match.team2_id, agree=True,
                    ).state, "completed",
                )
                self.assertTrue(process_tournament_transition(match.id))
            trans = RoundLifecycleTransition.objects.filter(round=round_obj).first()
            self.assertIsNotNone(trans, f"Missing lifecycle transition for {stage.name}")
            self.assertEqual(trans.status, RoundLifecycleTransition.COMPLETED, trans.last_error)
            print(
                f"TEAM_STAGES {stage.name} stage_round={stage_round_num} "
                f"complete={len(matches)} total_rounds={tournament.rounds.count()}",
                flush=True,
            )
            if stage == groups and stage_round_num == 3:
                self.assertEqual(
                    TournamentTeam.objects.filter(
                        tournament=tournament, current_stage_number=2, is_active=True
                    ).count(), 4, "Four qualifiers did not advance to final Stage",
                )
        tournament.refresh_from_db()
        self.assertEqual(tournament.automation_status, "completed")
        self.assertTrue(tournament.is_archived)
        self.assertEqual(
            LeaderboardEntry.objects.filter(leaderboard__tournament=tournament).count(), 4
        )
        print("TEAM_STAGES GROUPS+FINAL COMPLETE", flush=True)
