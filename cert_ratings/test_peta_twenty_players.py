"""20-player, five-round two-event Snake Draft regression (isolated DB).

Unlike the miniature 1-match-per-event fixture, this drives two configured
5-round tournaments, each with 20 participants, 5 doubles matches per round,
a genuinely frozen PFC-backed PETA entry rating and the automatic winner/loser
shuffle. Runs on isolated PostgreSQL in GitHub Actions, never production.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from cert_ratings.models import CertifyingEntity, CertRatingHistory, PlayerCertRating
from cert_ratings.peta_models import PetaCompetitor, PetaEvent, PetaEventEntry, PetaSeries
from courts.models import Court
from friendly_games.models import PlayerCodename
from matches.lifecycle import (
    process_tournament_transition,
    submit_official_result,
    validate_official_result,
)
from matches.models import Match, MatchPlayer, ScoreUpdate
from teams.models import Player, PlayerProfile, Team
from tournaments.lineup_lifecycle import (
    finalize_round_lineups,
    open_round_lineup_window,
)
from tournaments.models import (
    MeleePlayer,
    MeleeRoundAssignment,
    Round,
    Stage,
    Tournament,
)
from tournaments.partnership_models import MeleeShuffleHistory


class PetaTwentyPlayerFiveRoundTwoEventTests(TestCase):
    ROUNDS = 5
    PLAYERS = 20

    def setUp(self):
        self.entity = CertifyingEntity.objects.create(
            name="PETA snake CI", rating_system="peta_algorithm"
        )
        self.series = PetaSeries.objects.create(
            entity=self.entity, name="2 complete Snake Draft events"
        )
        self.players = []
        for idx, rating in enumerate((180,) * 5 + (140,) * 5 + (100,) * 5 + (80, 85, 90, 92, 95), 1):
            team = Team.objects.create(name=f"PETA snake HOME {idx}")
            player = Player.objects.create(name=f"PETA snake {idx}", team=team)
            PlayerProfile.objects.update_or_create(
                player=player, defaults={"value": float(rating)}
            )
            PlayerCodename.objects.get_or_create(player=player)
            self.players.append(player)

    def _prepare_event(self, ordinal):
        now = timezone.now()
        tournament = Tournament.objects.create(
            name=f"PETA full Snake event {ordinal}",
            format="multi_stage", play_format="doublets",
            is_melee=True, melee_format="doublets",
            shuffle_players_after_round=True,
            start_date=now, end_date=now + timedelta(hours=6),
            certifying_entity=self.entity,
        )
        stage = Stage.objects.create(
            tournament=tournament, stage_number=1,
            format="swiss", num_qualifiers=1,
            num_rounds_in_stage=self.ROUNDS,
        )
        for i in range(self.PLAYERS // 4):
            court = Court.objects.create(
                number=99000 + ordinal * 10 + i, is_available=True
            )
            tournament.courts.add(court)
        event = PetaEvent.objects.create(
            series=self.series, tournament=tournament,
            ordinal=ordinal, include_podium=True
        )
        for player in self.players:
            MeleePlayer.objects.create(tournament=tournament, player=player)
        self.assertEqual(tournament.generate_melee_teams("snake_draft"), self.PLAYERS // 2)
        tournament.refresh_from_db()
        self.assertEqual(tournament.melee_team_algorithm, "snake_draft")
        entries = dict(PetaEventEntry.objects.filter(event=event).values_list(
            "player_id", "entry_rating"
        ))
        self.assertEqual(len(entries), self.PLAYERS)
        self.assertEqual(tournament.generate_matches(), self.PLAYERS // 4)
        return tournament, stage, event, entries

    def _assert_first_snake_pairs(self, tournament, stage, entries):
        round_one = Round.objects.get(
            tournament=tournament, stage=stage, number_in_stage=1
        )
        assignment = list(MeleeRoundAssignment.objects.filter(
            tournament=tournament, round=round_one,
            state=MeleeRoundAssignment.ASSIGNED,
        ).values_list("team_id", "player_id"))
        self.assertEqual(len(assignment), self.PLAYERS)
        actual_pairs = {}
        for team_id, player_id in assignment:
            actual_pairs.setdefault(team_id, set()).add(player_id)
        self.assertEqual(sorted(map(len, actual_pairs.values())), [2] * (self.PLAYERS // 2))

        # Snake Draft pairs best-rated with worst-rated, using frozen
        # PETA entry snapshots, NOT a late read of PFC global rating.
        ranked = sorted(entries, key=lambda pid: (-entries[pid], pid))
        expected = {
            frozenset((ranked[pos], ranked[-pos-1]))
            for pos in range(self.PLAYERS // 2)
        }
        self.assertEqual(
            {frozenset(pair) for pair in actual_pairs.values()},
            expected,
        )

    def _play_full_event(self, tournament, stage, event):
        seen_match_ids = set()
        for round_number in range(1, self.ROUNDS + 1):
            current = Round.objects.get(
                tournament=tournament, stage=stage,
                number_in_stage=round_number,
            )
            matches = list(Match.objects.filter(
                tournament=tournament, round=current,
            ).order_by("pk"))
            self.assertEqual(
                len(matches), self.PLAYERS // 4, f"Round {round_number} must have five real matches"
            )
            open_round_lineup_window(current.pk)
            frozen = finalize_round_lineups(current.pk)
            self.assertTrue(frozen.frozen, frozen.blocked_match_ids)

            participants_this_round = set()
            for match in matches:
                match.refresh_from_db()
                self.assertEqual(match.status, "active")
                self.assertIsNotNone(match.court_id)
                roster = list(MatchPlayer.objects.filter(
                    match=match).values_list("player_id", flat=True))
                self.assertEqual(len(roster), 4)
                self.assertFalse(participants_this_round.intersection(roster))
                participants_this_round.update(roster)

                # Credited scorekeeper actually belongs to this concrete match.
                # Only the first round needs to qualify everyone for dividend.
                if round_number == 1:
                    scoreboard = match.live_scoreboard
                    for player_id in roster:
                        code = PlayerCodename.objects.get(player_id=player_id)
                        ScoreUpdate.objects.create(
                            scoreboard=scoreboard, team1_score=1,
                            team2_score=0, update_type="increment",
                            scorekeeper_codename=code.codename,
                        )

                scored_first = 13 if (match.pk + round_number) % 2 else 7
                scored_second = 7 if scored_first == 13 else 13
                submitted = submit_official_result(
                    match.pk, submitted_by_id=match.team1_id,
                    team1_score=scored_first, team2_score=scored_second,
                )
                self.assertEqual(submitted.state, "submitted")
                confirmed = validate_official_result(
                    match.pk, validating_team_id=match.team2_id, agree=True
                )
                self.assertEqual(confirmed.state, "completed")
                self.assertTrue(process_tournament_transition(match.pk))
                seen_match_ids.add(match.pk)

            self.assertEqual(len(participants_this_round), self.PLAYERS)
            current.refresh_from_db()
            self.assertTrue(current.is_complete)
            self.assertEqual(
                CertRatingHistory.objects.filter(
                    entity=self.entity, match_id__in=seen_match_ids).count(),
                4 * len(seen_match_ids),
            )
            if round_number < self.ROUNDS:
                successor = Round.objects.filter(
                    tournament=tournament, stage=stage,
                    number_in_stage=round_number + 1,
                    matches__isnull=False,
                )
                self.assertTrue(successor.exists(), "Snake Draft did not auto-advance")
                self.assertTrue(MeleeShuffleHistory.objects.filter(
                    tournament=tournament, round=current).exists())

        tournament.refresh_from_db()
        event.refresh_from_db()
        self.assertEqual(tournament.automation_status, "completed")
        self.assertIsNotNone(event.settled_at)
        self.assertEqual(len(seen_match_ids), (self.PLAYERS // 4) * self.ROUNDS)
        self.assertEqual(PetaEventEntry.objects.filter(
            event=event, end_rating__isnull=False).count(), self.PLAYERS)
        self.assertEqual(PetaEventEntry.objects.filter(
            event=event, eligible_for_dividend=True).count(), self.PLAYERS)

        # A replay of every already-completed match and the settlement
        # must not produce extra rating history or balance changes.
        before = dict(PetaCompetitor.objects.filter(
            series=self.series).values_list("player_id", "travel_points"))
        history_before = CertRatingHistory.objects.filter(
            entity=self.entity, match__tournament=tournament).count()
        for match_id in seen_match_ids:
            self.assertTrue(process_tournament_transition(match_id))
        self.assertEqual(CertRatingHistory.objects.filter(
            entity=self.entity, match__tournament=tournament).count(),
            history_before)
        self.assertEqual(before, dict(PetaCompetitor.objects.filter(
            series=self.series).values_list("player_id", "travel_points")))
        self.assertEqual(history_before, self.PLAYERS * self.ROUNDS)
        self.assertEqual(
            Decimal(event.settlement_audit["pool"]),
            Decimal(event.settlement_audit["distributed"])
            + Decimal(event.settlement_audit["undistributed"]),
        )
        return {row.player_id: row for row in PetaEventEntry.objects.filter(event=event)}

    def test_twenty_players_five_rounds_two_events(self):
        first, stage1, event1, first_entries = self._prepare_event(1)
        self._assert_first_snake_pairs(first, stage1, first_entries)
        ends1 = self._play_full_event(first, stage1, event1)

        # Between events: lower one global PFC value and raise another.
        dropping, rising = self.players[0], self.players[-1]
        previous_drop = ends1[dropping.pk].end_rating
        previous_rise = ends1[rising.pk].end_rating
        PlayerProfile.objects.filter(player=dropping).update(
            value=previous_drop - 75)
        PlayerProfile.objects.filter(player=rising).update(
            value=previous_rise + 35)

        second, stage2, event2, second_entries = self._prepare_event(2)
        self.assertAlmostEqual(second_entries[dropping.pk], previous_drop)
        self.assertAlmostEqual(second_entries[rising.pk], previous_rise + 35)
        self._assert_first_snake_pairs(second, stage2, second_entries)
        self._play_full_event(second, stage2, event2)

        self.assertEqual(PetaEvent.objects.filter(
            series=self.series, settled_at__isnull=False).count(), 2)
        self.assertEqual(PetaEventEntry.objects.filter(
            event__series=self.series).count(), 2 * self.PLAYERS)
        self.assertEqual(CertRatingHistory.objects.filter(
            entity=self.entity, match__tournament__in=[first, second]).count(),
            2 * self.ROUNDS * self.PLAYERS)
