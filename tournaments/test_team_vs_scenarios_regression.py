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
