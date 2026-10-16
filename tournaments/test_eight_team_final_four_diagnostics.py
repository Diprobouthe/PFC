"""Eight-team Swiss→Final Four and ordinary Admin Knockout diagnostics.

No production mutations: Django creates and destroys disposable PostgreSQL DB.
These tests intentionally assert the actual winner-first podium and real Round
handoffs, not merely row counts or the presence of a published leaderboard.
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from courts.models import Court, CourtComplex
from leaderboards.models import LeaderboardEntry
from matches.lifecycle import (
    process_tournament_transition, submit_official_result, validate_official_result,
)
from matches.models import Match, MatchPlayer
from simple_creator.models import ScenarioStage, TournamentScenario
from signin.services import activate_team_tournament_signin
from teams.models import Player, Team
from tournaments.lineup_lifecycle import finalize_round_lineups
from tournaments.models import (
    Round, RoundLifecycleTransition, Stage, Tournament, TournamentTeam,
    PlayerTournamentAchievement,
)


class EightTeamTournamentDiagnosticTests(TestCase):
    def setUp(self):
        self.complex = CourtComplex.objects.create(
            name="8-team isolated final four", description="Temporary test only"
        )
        courts = [
            Court.objects.create(number=99100 + i, is_available=True)
            for i in range(4)
        ]
        self.complex.courts.add(*courts)
        self.teams = []
        for i in range(8):
            team = Team.objects.create(name=f"Eight-Team {i+1:02}", pin=f"99{i+1:04}")
            self.teams.append(team)
            for p in range(2):
                Player.objects.create(name=f"Eight-P {i+1}-{p}", team=team)

    def _complete_round(self, round_obj, *, choose_winner):
        matches = list(Match.objects.filter(round=round_obj).order_by("id"))
        round_obj.refresh_from_db()
        if round_obj.tournament.lineup_selection_seconds:
            self.assertIsNotNone(round_obj.lineup_deadline_at)
            remaining = (round_obj.lineup_deadline_at - timezone.now()).total_seconds()
            self.assertGreater(remaining, 0)
            self.assertLessEqual(
                remaining, round_obj.tournament.lineup_selection_seconds,
            )
            before_deadline = finalize_round_lineups(round_obj.id)
            self.assertFalse(before_deadline.frozen)
            self.assertEqual(
                Match.objects.filter(round=round_obj, status="pending").count(),
                len(matches), "Matches activated before lineup deadline",
            )
            # Simulate passage of 120 seconds deterministically; no real wait,
            # no production clock or database.
            with patch(
                "tournaments.lineup_lifecycle.timezone.now",
                return_value=round_obj.lineup_deadline_at + timedelta(seconds=1),
            ):
                result = finalize_round_lineups(round_obj.id)
        else:
            result = finalize_round_lineups(round_obj.id)
        self.assertTrue(
            result.frozen,
            f"Round {round_obj.id}: invalid roster: {result.blocked_match_ids}",
        )
        self.assertEqual(len(result.ready_match_ids), len(matches))
        losers = []
        winners = []
        for match in matches:
            match.refresh_from_db()
            self.assertEqual(match.status, "active")
            self.assertIsNotNone(match.court_id)
            self.assertEqual(MatchPlayer.objects.filter(match=match).count(), 4)
            winner_id = choose_winner(match)
            self.assertIn(winner_id, (match.team1_id, match.team2_id))
            scores = (13, 7) if winner_id == match.team1_id else (7, 13)
            submission = submit_official_result(
                match.id, submitted_by_id=match.team1_id,
                team1_score=scores[0], team2_score=scores[1],
            )
            self.assertEqual(submission.state, "submitted")
            validation = validate_official_result(
                match.id, validating_team_id=match.team2_id, agree=True
            )
            self.assertEqual(validation.state, "completed")
            self.assertTrue(process_tournament_transition(match.id))
            match.refresh_from_db()
            self.assertEqual(match.winner_id, winner_id)
            winners.append(winner_id)
            losers.append(
                match.team2_id if winner_id == match.team1_id else match.team1_id
            )
        trans = RoundLifecycleTransition.objects.filter(round=round_obj).first()
        self.assertIsNotNone(trans, f"No persisted Round transition {round_obj.id}")
        self.assertEqual(trans.status, RoundLifecycleTransition.COMPLETED, trans.last_error)
        return winners, losers

    def test_swiss_8_to_4_semifinals_final_and_champion_ranked_first(self):
        scenario = TournamentScenario.objects.create(
            name="e2e-eight-to-finalfour",
            display_name="E2E 8 Swiss Final Four",
            description="8 teams -> Swiss x3 -> top 4 -> semifinals -> final",
            default_court_complex=self.complex,
            scenario_mode="team", tournament_type="swiss",
            num_rounds=3, draft_type="random",
            is_free=True, requires_voucher=False,
            max_courts=4, recommended_courts=4,
            lineup_selection_seconds=0,
        )
        ScenarioStage.objects.create(
            scenario=scenario, stage_number=1, name="Swiss qualification",
            format="swiss", num_rounds_in_stage=3, num_qualifiers=4,
        )
        ScenarioStage.objects.create(
            scenario=scenario, stage_number=2, name="Final Four",
            format="knockout", num_rounds_in_stage=2, num_qualifiers=0,
        )
        response = self.client.post(reverse("create_simple_tournament"), {
            "scenario": scenario.name, "format": "doubles", "num_courts": "4",
        })
        self.assertEqual(response.status_code, 302)
        tournament = Tournament.objects.filter(
            name__startswith=scenario.display_name
        ).order_by("-pk").first()
        self.assertIsNotNone(tournament)
        self.assertEqual(
            list(tournament.stages.order_by("stage_number").values_list(
                "format", "num_rounds_in_stage", "num_qualifiers",
            )),
            [("swiss", 3, 4), ("knockout", 2, 0)],
        )
        swiss, final_four = list(tournament.stages.order_by("stage_number"))
        for team in self.teams:
            activate_team_tournament_signin(team=team, tournament=tournament)
        self.assertEqual(
            self.client.post(
                reverse("start_tournament", args=[tournament.id])
            ).status_code, 302,
        )
        for round_number in (1, 2, 3):
            round_obj = Round.objects.filter(
                tournament=tournament, stage=swiss,
                number_in_stage=round_number,
            ).first()
            self.assertIsNotNone(round_obj, f"Swiss round {round_number} missing")
            self.assertEqual(Match.objects.filter(round=round_obj).count(), 4)
            winners, losers = self._complete_round(
                round_obj, choose_winner=lambda match: match.team1_id
            )
            print(
                f"EIGHT_TEAM SWISS round={round_number} "
                f"matches=4 winners={winners} losers={losers}",
                flush=True,
            )

        advanced = list(TournamentTeam.objects.filter(
            tournament=tournament, current_stage_number=2, is_active=True
        ).order_by("-swiss_points", "-buchholz_score", "id"))
        self.assertEqual(len(advanced), 4, "Swiss did not qualify exactly 4 of 8 teams")
        qualifier_ids = {tt.team_id for tt in advanced}
        swiss_points = {tt.team_id: tt.swiss_points for tt in advanced}
        excluded = TournamentTeam.objects.filter(
            tournament=tournament, current_stage_number=1, is_active=False
        )
        self.assertEqual(excluded.count(), 4)
        print(
            f"EIGHT_TEAM QUALIFIERS ids={sorted(qualifier_ids)} "
            f"swiss_points={swiss_points}",
            flush=True,
        )

        semi_round = Round.objects.filter(
            tournament=tournament, stage=final_four, number_in_stage=1
        ).first()
        self.assertIsNotNone(semi_round, "Final Four semifinals missing")
        semis = list(Match.objects.filter(round=semi_round).order_by("id"))
        self.assertEqual(len(semis), 2)
        self.assertEqual(
            {id for match in semis for id in (match.team1_id, match.team2_id)},
            qualifier_ids, "Semifinals did not use exactly the 4 Swiss qualifiers",
        )
        # Force lower-seeded semifinal victories to expose any assumption
        # that Swiss points, rather than the final Match, decide the podium.
        semi_winners, semi_losers = self._complete_round(
            semi_round,
            choose_winner=lambda match: min(
                (match.team1_id, match.team2_id),
                key=lambda tid: (swiss_points[tid], tid),
            ),
        )
        final_round = Round.objects.filter(
            tournament=tournament, stage=final_four, number_in_stage=2
        ).first()
        self.assertIsNotNone(final_round, "Final Four championship final missing")
        finals = list(Match.objects.filter(round=final_round))
        self.assertEqual(len(finals), 1)
        final_match = finals[0]
        self.assertEqual(
            {final_match.team1_id, final_match.team2_id},
            set(semi_winners), "Final did not use exactly the two semifinal winners",
        )
        champion = min(
            semi_winners, key=lambda tid: (swiss_points[tid], tid)
        )
        runner_up = next(tid for tid in semi_winners if tid != champion)
        self._complete_round(
            final_round, choose_winner=lambda match: champion,
        )
        final_match.refresh_from_db()
        self.assertEqual(final_match.winner_id, champion)

        tournament.refresh_from_db()
        self.assertEqual(tournament.automation_status, "completed")
        self.assertTrue(tournament.is_archived)
        self.assertEqual(Match.objects.filter(tournament=tournament).count(), 15)
        entries = list(
            LeaderboardEntry.objects.filter(
                leaderboard__tournament=tournament
            ).order_by("position")
        )
        self.assertEqual(len(entries), 8)
        print(
            "EIGHT_TEAM PODIUM "
            f"champion={champion} runner_up={runner_up} "
            f"semifinal_losers={semi_losers} "
            f"published_top4={[(e.team_id,e.position,e.tournament_status) for e in entries[:4]]} "
            f"third_place_match={'absent' if Match.objects.filter(tournament=tournament,round__stage=final_four).count()==3 else 'CHECK'}",
            flush=True,
        )
        self.assertEqual(
            entries[0].team_id, champion,
            "Winner of championship final must be #1 regardless of Swiss points",
        )
        self.assertEqual(
            entries[1].team_id, runner_up,
            "Loser of championship final must be #2",
        )
        self.assertEqual(
            {e.team_id for e in entries[2:4]}, set(semi_losers),
            "Semifinal losers should occupy #3 and #4 pending a bronze match",
        )
        self.assertEqual(
            entries[0].tournament_status, "champion",
            "The winner must be marked champion, not active",
        )
        self.assertEqual(
            entries[1].tournament_status, "finalist",
            "The runner-up must be marked finalist, not active",
        )
        self.assertEqual(
            [e.official_place for e in entries[:4]], [1, 2, 3, 3],
            "CEP model requires two official joint bronze positions",
        )
        self.assertEqual(
            {e.tournament_status for e in entries[2:4]}, {"shared_third"},
        )
        self.assertEqual(
            PlayerTournamentAchievement.objects.filter(
                tournament=tournament,
                award_type=PlayerTournamentAchievement.MEDAL_BRONZE,
            ).count(), 4, "Both semifinal-losing doublets must get bronze",
        )

    def test_optional_bronze_match_finalizes_only_after_both_finals(self):
        """8 Swiss → 4 knockout → championship + bronze in one terminal Round."""
        scenario = TournamentScenario.objects.create(
            name="e2e-eight-bronze-option",
            display_name="E2E 8 Swiss Played Bronze",
            description="3 Swiss + two finals",
            default_court_complex=self.complex,
            scenario_mode="team", tournament_type="swiss",
            num_rounds=3, draft_type="random",
            is_free=True, requires_voucher=False,
            max_courts=4, recommended_courts=4,
            lineup_selection_seconds=120,
        )
        ScenarioStage.objects.create(
            scenario=scenario, stage_number=1, name="Swiss",
            format="swiss", num_rounds_in_stage=3, num_qualifiers=4,
        )
        ScenarioStage.objects.create(
            scenario=scenario, stage_number=2, name="Final Four",
            format="knockout", num_rounds_in_stage=2, num_qualifiers=0,
            third_place_playoff=True,
        )
        response = self.client.post(reverse("create_simple_tournament"), {
            "scenario": scenario.name, "format": "doubles", "num_courts": "4",
        })
        self.assertEqual(response.status_code, 302)
        tournament = Tournament.objects.filter(
            name__startswith=scenario.display_name
        ).order_by("-pk").first()
        self.assertIsNotNone(tournament)
        swiss, final_four = list(tournament.stages.order_by("stage_number"))
        self.assertTrue(final_four.third_place_playoff)
        for team in self.teams:
            activate_team_tournament_signin(team=team, tournament=tournament)
        self.assertEqual(
            self.client.post(
                reverse("start_tournament", args=[tournament.id])
            ).status_code, 302,
        )
        for number in (1, 2, 3):
            playing_round = Round.objects.get(
                tournament=tournament, stage=swiss, number_in_stage=number,
            )
            self.assertEqual(Match.objects.filter(round=playing_round).count(), 4)
            self._complete_round(
                playing_round, choose_winner=lambda match: match.team1_id,
            )
        qualifiers = set(TournamentTeam.objects.filter(
            tournament=tournament, current_stage_number=2, is_active=True,
        ).values_list("team_id", flat=True))
        self.assertEqual(len(qualifiers), 4)
        semi_round = Round.objects.get(
            tournament=tournament, stage=final_four, number_in_stage=1,
        )
        semifinal_matches = list(Match.objects.filter(round=semi_round))
        self.assertEqual(len(semifinal_matches), 2)
        self.assertEqual(
            {tid for m in semifinal_matches for tid in (m.team1_id, m.team2_id)},
            qualifiers,
        )
        semi_winners, semi_losers = self._complete_round(
            semi_round, choose_winner=lambda match: match.team1_id,
        )
        final_round = Round.objects.get(
            tournament=tournament, stage=final_four, number_in_stage=2,
        )
        final = Match.objects.get(round=final_round, placement_role="championship_final")
        bronze = Match.objects.get(round=final_round, placement_role="third_place_playoff")
        self.assertEqual(
            {final.team1_id, final.team2_id}, set(semi_winners),
        )
        self.assertEqual(
            {bronze.team1_id, bronze.team2_id}, set(semi_losers),
        )
        self.assertEqual(Match.objects.filter(round=final_round).count(), 2)
        self.assertEqual(tournament.lineup_selection_seconds, 120)
        final_round.refresh_from_db()
        self.assertIsNotNone(final_round.lineup_deadline_at)
        remaining = (final_round.lineup_deadline_at - timezone.now()).total_seconds()
        self.assertGreater(remaining, 0)
        self.assertLessEqual(remaining, 120)
        before_deadline = finalize_round_lineups(final_round.id)
        self.assertFalse(before_deadline.frozen)
        self.assertEqual(
            Match.objects.filter(round=final_round, status="pending").count(),
            2, "Neither final may activate before the shared lineup deadline",
        )
        with patch(
            "tournaments.lineup_lifecycle.timezone.now",
            return_value=final_round.lineup_deadline_at + timedelta(seconds=1),
        ):
            freeze = finalize_round_lineups(final_round.id)
        self.assertTrue(freeze.frozen)
        self.assertEqual(len(freeze.ready_match_ids), 2)

        def complete_one(match):
            match.refresh_from_db()
            self.assertEqual(match.status, "active")
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

        # Championship has ended, but bronze remains unresolved: no completion.
        complete_one(final)
        tournament.refresh_from_db()
        self.assertNotEqual(tournament.automation_status, "completed")
        self.assertFalse(tournament.is_archived)
        complete_one(bronze)
        tournament.refresh_from_db()
        self.assertEqual(tournament.automation_status, "completed")
        self.assertTrue(tournament.is_archived)
        self.assertEqual(Match.objects.filter(tournament=tournament).count(), 16)
        ranks = list(
            LeaderboardEntry.objects.filter(
                leaderboard__tournament=tournament,
            ).order_by("position")
        )
        self.assertEqual(len(ranks), 8)
        self.assertEqual(
            [e.official_place for e in ranks[:4]], [1, 2, 3, 4],
        )
        self.assertEqual(ranks[0].team_id, final.team1_id)
        self.assertEqual(ranks[1].team_id, final.team2_id)
        self.assertEqual(ranks[2].team_id, bronze.team1_id)
        self.assertEqual(ranks[3].team_id, bronze.team2_id)
        self.assertEqual(
            [e.tournament_status for e in ranks[:4]],
            ["champion", "finalist", "third_place", "fourth_place"],
        )
        self.assertEqual(
            PlayerTournamentAchievement.objects.filter(
                tournament=tournament,
                award_type=PlayerTournamentAchievement.MEDAL_BRONZE,
            ).count(), 2, "Only winning bronze doublet earns bronze",
        )
        self.assertTrue(process_tournament_transition(bronze.id))
        self.assertEqual(Match.objects.filter(tournament=tournament).count(), 16)
        print(
            f"EIGHT_TEAM_BRONZE MATCHES=16 ranks={[e.official_place for e in ranks[:4]]}",
            flush=True,
        )

    def test_ordinary_knockout_8_teams_generates_winner_only_successor(self):
        """Control test for the non-Scenario ordinary Tournament model path."""
        now = timezone.now()
        tournament = Tournament.objects.create(
            name="E2E Admin-style pure knockout with 8 teams",
            format="knockout", play_format="doublets",
            has_doublets=True,
            start_date=now, end_date=now + timedelta(hours=4),
            lineup_selection_seconds=0,
        )
        for court in self.complex.courts.all():
            tournament.courts.add(court)
        for team in self.teams:
            activate_team_tournament_signin(team=team, tournament=tournament)
        created = tournament.generate_matches()
        self.assertEqual(created, 4, "Ordinary Tournament first round was not generated")
        first = Round.objects.filter(tournament=tournament, number=1).first()
        self.assertIsNotNone(first)
        self.assertEqual(Match.objects.filter(round=first).count(), 4)
        winners, losers = self._complete_round(
            first, choose_winner=lambda match: match.team1_id
        )
        second = Round.objects.filter(tournament=tournament, number=2).first()
        self.assertIsNotNone(
            second, "Ordinary non-Scenario Knockout did not generate quarterfinal winners' semifinals"
        )
        semis = list(Match.objects.filter(round=second))
        self.assertEqual(len(semis), 2)
        self.assertEqual(
            {tid for match in semis for tid in (match.team1_id, match.team2_id)},
            set(winners),
        )
        print(
            f"EIGHT_TEAM ADMIN_KNOCKOUT round2 winner_ids={winners} "
            f"lineup_deadline={second.lineup_deadline_at}", flush=True,
        )
        self.assertIsNotNone(
            second.lineup_deadline_at,
            "Ordinary Knockout next Round has no lineup deadline, so teams cannot "
            "freeze official lineups and activate Courts normally",
        )
