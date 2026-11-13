"""20-player, five-round two-event Snake Draft regression (isolated DB).

Unlike the miniature 1-match-per-event fixture, this drives two configured
5-round tournaments, each with 20 participants, 5 doubles matches per round,
a genuinely frozen PFC-backed PETA entry rating and the automatic winner/loser
shuffle. Runs on isolated PostgreSQL in GitHub Actions, never production.
"""
from datetime import timedelta
from decimal import Decimal
from random import Random

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
    TournamentTeam,
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

    def _play_full_event(self, tournament, stage, event, rng=None):
        seen_match_ids = set()
        for round_number in range(1, self.ROUNDS + 1):
            current = Round.objects.get(
                tournament=tournament, stage=stage,
                number_in_stage=round_number,
            )
            matches = list(Match.objects.filter(
                tournament=tournament, round=current,
            ).order_by("pk"))
            active_team_ids = list(TournamentTeam.objects.filter(
                tournament=tournament, current_stage_number=stage.stage_number,
                is_active=True).values_list("team_id", flat=True))
            assignments = list(MeleeRoundAssignment.objects.filter(
                tournament=tournament, round=current).values_list(
                "player_id", "team_id", "state"))
            self.assertEqual(
                len(matches), self.PLAYERS // 4,
                f"Round {round_number} must have five real matches; "
                f"active_teams={len(active_team_ids)} IDs={active_team_ids}; "
                f"assignments={assignments}; match_ids={[m.pk for m in matches]}"
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
                # Every played match needs a real contribution for dividend.
                scoreboard = match.live_scoreboard
                for player_id in roster:
                    code = PlayerCodename.objects.get(player_id=player_id)
                    ScoreUpdate.objects.create(
                        scoreboard=scoreboard, team1_score=1,
                        team2_score=0, update_type="increment",
                        scorekeeper_codename=code.codename,
                    )

                if rng is None:
                    scored_first = 13 if (match.pk + round_number) % 2 else 7
                    scored_second = 7 if scored_first == 13 else 13
                else:
                    # Hidden skill determines the odds; randomness represents
                    # match-day variance, not a 50/50 coin toss.
                    skill = getattr(self, "_simulation_skill", None)
                    if skill is None:
                        loser_score = rng.randint(0, 12)
                        scored_first, scored_second = ((13, loser_score)
                            if rng.randrange(2) else (loser_score, 13))
                    else:
                        side1 = list(MeleeRoundAssignment.objects.filter(
                            tournament=tournament, round=current,
                            team_id=match.team1_id,
                            state=MeleeRoundAssignment.ASSIGNED,
                        ).values_list("player_id", flat=True))
                        side2 = list(MeleeRoundAssignment.objects.filter(
                            tournament=tournament, round=current,
                            team_id=match.team2_id,
                            state=MeleeRoundAssignment.ASSIGNED,
                        ).values_list("player_id", flat=True))
                        self.assertEqual((len(side1), len(side2)), (2, 2))
                        gap = sum(skill[p] for p in side1) / 2 - sum(
                            skill[p] for p in side2) / 2
                        probability_first = 1 / (1 + 10 ** (-gap / 65))
                        first_wins = rng.random() < probability_first
                        # Stronger mismatches tend toward wider margins,
                        # while upsets and close games remain possible.
                        expected_margin = min(11, 2 + abs(gap) / 12)
                        margin = max(1, min(13, round(
                            rng.gauss(expected_margin, 3.2))))
                        loser_score = 13 - margin
                        scored_first, scored_second = (
                            (13, loser_score) if first_wins
                            else (loser_score, 13))
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
        self.assertAlmostEqual(second_entries[rising.pk], previous_rise)
        self._assert_first_snake_pairs(second, stage2, second_entries)
        self._play_full_event(second, stage2, event2)

        self.assertEqual(PetaEvent.objects.filter(
            series=self.series, settled_at__isnull=False).count(), 2)
        self.assertEqual(PetaEventEntry.objects.filter(
            event__series=self.series).count(), 2 * self.PLAYERS)
        self.assertEqual(CertRatingHistory.objects.filter(
            entity=self.entity, match__tournament__in=[first, second]).count(),
            2 * self.ROUNDS * self.PLAYERS)

    def test_four_events_with_new_100_rating_player_entering_third(self):
        """Real Django/PostgreSQL lifecycle: 4 x 5 rounds, late entry and once-only settlement."""
        # The established roster includes 100, 140 and 180 rating cohorts.
        # Substitute one player in event three to keep 20 participants / 5 matches per round.
        original = self.players[-1]
        entrant_team = Team.objects.create(name="PETA late entrant HOME")
        entrant = Player.objects.create(name="PETA late entrant 100", team=entrant_team)
        PlayerProfile.objects.update_or_create(
            player=entrant, defaults={"value": 100.0}
        )
        PlayerCodename.objects.get_or_create(player=entrant)

        previous_ends = {}
        permanent_row_ids = {}
        event_ids = []
        tournament_ids = []
        for ordinal in range(1, 5):
            if ordinal == 3:
                self.players[-1] = entrant
            tournament, stage, event, entries = self._prepare_event(ordinal)
            event_ids.append(event.pk)
            tournament_ids.append(tournament.pk)
            self._assert_first_snake_pairs(tournament, stage, entries)
            # A returning player must keep the SAME permanent competitor row.
            # Each event gets a distinct historical entry, not a second account.
            permanent = dict(PetaCompetitor.objects.filter(
                series=self.series, player_id__in=entries
            ).values_list('player_id', 'pk'))
            self.assertEqual(set(permanent), set(entries))
            for player_id, row_id in permanent.items():
                if player_id in permanent_row_ids:
                    self.assertEqual(row_id, permanent_row_ids[player_id])
                else:
                    permanent_row_ids[player_id] = row_id
            self.assertEqual(PetaCompetitor.objects.filter(
                series=self.series).count(), len(permanent_row_ids))
            if ordinal < 3:
                self.assertNotIn(entrant.pk, entries)
            else:
                self.assertIn(entrant.pk, entries)
                if ordinal == 3:
                    self.assertAlmostEqual(float(entries[entrant.pk]), 100.0)
                    self.assertFalse(PetaEventEntry.objects.filter(
                        event__ordinal__lt=3, player=entrant
                    ).exists())
                else:
                    self.assertAlmostEqual(
                        float(entries[entrant.pk]),
                        float(previous_ends[entrant.pk])
                    )
            for player_id, prior_end in previous_ends.items():
                if player_id in entries:
                    self.assertAlmostEqual(
                        float(entries[player_id]), float(prior_end)
                    )
            ends = self._play_full_event(tournament, stage, event)
            previous_ends = {pid: entry.end_rating for pid, entry in ends.items()}
            for player_id, end_rating in previous_ends.items():
                competitor = PetaCompetitor.objects.get(
                    series=self.series, player_id=player_id)
                self.assertAlmostEqual(float(competitor.last_end_rating),
                                       float(end_rating))

        self.assertEqual(PetaEvent.objects.filter(
            pk__in=event_ids, settled_at__isnull=False
        ).count(), 4)
        self.assertEqual(PetaEventEntry.objects.filter(
            event_id__in=event_ids
        ).count(), 4 * self.PLAYERS)
        self.assertEqual(PetaEventEntry.objects.filter(
            event_id__in=event_ids, player=entrant
        ).count(), 2)
        self.assertEqual(CertRatingHistory.objects.filter(
            entity=self.entity, match__tournament_id__in=tournament_ids
        ).count(), 4 * self.ROUNDS * self.PLAYERS)

    def test_odd_rosters_have_explicit_individual_byes(self):
        """19/21 player Snake Draft must preserve all entrants, never silently lose one."""
        for count in (19, 21):
            with self.subTest(players=count):
                # A fresh TestCase transaction rolls back at test end; each
                # tournament and its round assignments remain independent.
                roster = list(self.players[:min(count, len(self.players))])
                if count == 21:
                    team = Team.objects.create(name="PETA odd roster HOME")
                    extra = Player.objects.create(name="PETA odd roster extra", team=team)
                    PlayerProfile.objects.update_or_create(
                        player=extra, defaults={"value": 100.0}
                    )
                    PlayerCodename.objects.get_or_create(player=extra)
                    roster.append(extra)
                now = timezone.now()
                tournament = Tournament.objects.create(
                    name=f"PETA odd roster {count}", format="multi_stage",
                    play_format="doublets", is_melee=True, melee_format="doublets",
                    shuffle_players_after_round=True, start_date=now,
                    end_date=now + timedelta(hours=6),
                    certifying_entity=self.entity,
                )
                stage = Stage.objects.create(
                    tournament=tournament, stage_number=1, format="swiss",
                    num_qualifiers=1, num_rounds_in_stage=self.ROUNDS,
                )
                for i in range(6):
                    tournament.courts.add(Court.objects.create(
                        number=99500 + count * 10 + i, is_available=True
                    ))
                # A PETA entity owns exactly one series. Give each independent
                # unfinished BYE fixture its own entity and series.
                isolated_entity = CertifyingEntity.objects.create(
                    name=f"PETA odd roster entity {count}",
                    rating_system="peta_algorithm"
                )
                tournament.certifying_entity = isolated_entity
                tournament.save(update_fields=["certifying_entity"])
                isolated_series = PetaSeries.objects.create(
                    entity=isolated_entity, name=f"Odd roster fixture {count}"
                )
                PetaEvent.objects.create(
                    series=isolated_series, tournament=tournament,
                    ordinal=1, include_podium=True
                )
                for player in roster:
                    MeleePlayer.objects.create(tournament=tournament, player=player)
                tournament.generate_melee_teams("snake_draft")
                round_one = Round.objects.get(
                    tournament=tournament, stage=stage, number_in_stage=1
                )
                assignments = list(MeleeRoundAssignment.objects.filter(
                    tournament=tournament, round=round_one
                ))
                self.assertEqual(len(assignments), count)
                self.assertEqual(
                    {row.player_id for row in assignments},
                    {player.pk for player in roster},
                )
                self.assertEqual(
                    PetaEventEntry.objects.filter(
                        event__tournament=tournament
                    ).count(), count
                )

    def _run_skill_simulation(self, seed):
        """8 actual five-round events; 800 player-match rating writes.

        Skill-weighted scores, staggered 120/140/180 entrants, and
        returners after gaps. Global PFC intentionally changes between events.
        """
        rng = Random(seed)
        original = list(self.players)
        newcomers = []
        for idx, rating in enumerate((120, 180, 140, 180, 120, 180), 1):
            team = Team.objects.create(name=f"PETA rotating HOME {idx}")
            player = Player.objects.create(
                name=f"PETA late entrant {idx} rating {rating}", team=team)
            PlayerProfile.objects.update_or_create(
                player=player, defaults={"value": float(rating)})
            PlayerCodename.objects.get_or_create(player=player)
            newcomers.append(player)

        rosters = [
            original,
            original,
            original[:19] + [newcomers[0]],           # 120 enters
            original[:18] + [newcomers[0], newcomers[1]],  # 180 enters
            original[:17] + [newcomers[0], newcomers[1], newcomers[2]],
            original[:17] + [newcomers[1], newcomers[2], newcomers[3]],
            original[:16] + [newcomers[1], newcomers[2], newcomers[3], newcomers[4]],
            original[:15] + [newcomers[1], newcomers[2], newcomers[3],
                             newcomers[4], newcomers[5]],  # late 180
        ]
        # Ground truth is immutable and invisible to PETA calculations.
        self._simulation_skill = {
            player.pk: float(PlayerProfile.objects.get(player=player).value)
            for player in original + newcomers
        }
        last_end = {}
        permanent_ids = {}
        all_event_ids = []
        for ordinal, roster in enumerate(rosters, 1):
            self.players = list(roster)
            self.assertEqual(len({p.pk for p in roster}), self.PLAYERS)
            # Deliberately scramble global PFC: returning PETA players must
            # ignore it, whereas newcomers must use their initial PFC.
            if ordinal > 1:
                for player in roster:
                    if player.pk in last_end:
                        PlayerProfile.objects.filter(player=player).update(
                            value=float(last_end[player.pk]) + rng.randint(-35, 35))
            tournament, stage, event, entries = self._prepare_event(ordinal)
            all_event_ids.append(event.pk)
            self._assert_first_snake_pairs(tournament, stage, entries)
            for player in roster:
                expected = last_end.get(player.pk)
                if expected is None:
                    expected = PlayerProfile.objects.get(player=player).value
                self.assertAlmostEqual(float(entries[player.pk]), float(expected))
                competitor = PetaCompetitor.objects.get(
                    series=self.series, player=player)
                if player.pk in permanent_ids:
                    self.assertEqual(competitor.pk, permanent_ids[player.pk])
                permanent_ids[player.pk] = competitor.pk
            self.assertEqual(PetaCompetitor.objects.filter(
                series=self.series).count(), len(permanent_ids))
            end_entries = self._play_full_event(
                tournament, stage, event, rng=rng)
            snapshot = sorted(
                ((next(p.name for p in roster if p.pk == pid),
                  float(entry.entry_rating), float(entry.end_rating))
                 for pid, entry in end_entries.items()),
                key=lambda item: -item[2],
            )
            print(
                "PETA_SIM_EVENT", ordinal, f"seed={seed}",
                "players=20", "matches=25",
                "top5=" + repr([(name, round(start, 2), round(end, 2))
                                  for name, start, end in snapshot[:5]]),
                "bottom5=" + repr([(name, round(start, 2), round(end, 2))
                                     for name, start, end in snapshot[-5:]]),
                flush=True,
            )
            for pid, entry in end_entries.items():
                last_end[pid] = entry.end_rating
                self.assertAlmostEqual(
                    float(PetaCompetitor.objects.get(
                        series=self.series, player_id=pid).last_end_rating),
                    float(entry.end_rating))
        self.assertEqual(PetaEvent.objects.filter(
            pk__in=all_event_ids, settled_at__isnull=False).count(), 8)
        self.assertEqual(PetaEventEntry.objects.filter(
            event_id__in=all_event_ids).count(), 160)
        self.assertEqual(CertRatingHistory.objects.filter(
            entity=self.entity).count(), 8 * self.ROUNDS * self.PLAYERS)
        for entrant in newcomers:
            self.assertEqual(PetaEventEntry.objects.filter(
                event__series=self.series, player=entrant,
                event__ordinal__lt=3).count(), 0)

    def test_skill_simulation_seed_20261114(self):
        self._run_skill_simulation(20261114)

    def test_skill_simulation_seed_20261115(self):
        self._run_skill_simulation(20261115)
