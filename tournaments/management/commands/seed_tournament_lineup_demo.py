"""Seed a disposable Tournament lineup-window demo in the active database."""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from courts.models import Court, CourtComplex
from friendly_games.models import PlayerCodename
from matches.models import Match
from teams.models import Player, Team
from tournaments.lineup_lifecycle import open_round_lineup_window
from tournaments.models import Round, Tournament, TournamentCourt, TournamentTeam


DEMO_TOURNAMENT_NAME = "PFC Sandbox Timed Lineup Demo"


class Command(BaseCommand):
    help = "Create a disposable 20-player Tournament Round lineup/court-allocation demo."

    def add_arguments(self, parser):
        parser.add_argument("--lineup-seconds", type=int, default=120)
        parser.add_argument("--courts", type=int, default=2)
        parser.add_argument("--reset", action="store_true")

    @transaction.atomic
    def handle(self, *args, **options):
        seconds = max(0, options["lineup_seconds"])
        court_count = max(1, options["courts"])
        now = timezone.now()

        tournament, created = Tournament.objects.get_or_create(
            name=DEMO_TOURNAMENT_NAME,
            defaults={
                "format": "round_robin",
                "play_format": "doublets",
                "has_doublets": True,
                "allowed_match_types": {"allowed_match_types": ["doublet"]},
                "lineup_selection_seconds": seconds,
                "start_date": now,
                "end_date": now + timedelta(hours=8),
            },
        )
        if options["reset"] and not created:
            Match.objects.filter(tournament=tournament).delete()
            tournament.rounds.all().delete()
            tournament.tournamentteam_set.all().delete()
            tournament.tournamentcourt_set.all().delete()
        tournament.lineup_selection_seconds = seconds
        tournament.has_doublets = True
        tournament.allowed_match_types = {"allowed_match_types": ["doublet"]}
        tournament.save(update_fields=["lineup_selection_seconds", "has_doublets", "allowed_match_types", "updated_at"])

        complex_obj, _ = CourtComplex.objects.get_or_create(
            name="PFC Sandbox Tournament Complex",
            defaults={"description": "Isolated manual test venue."},
        )
        courts = []
        for index in range(1, court_count + 1):
            court, _ = Court.objects.get_or_create(
                number=97000 + index,
                defaults={"name": f"Demo Court {index}", "is_available": True},
            )
            court.name = f"Demo Court {index}"
            court.is_available = True
            court.save(update_fields=["name", "is_available"])
            complex_obj.courts.add(court)
            TournamentCourt.objects.get_or_create(tournament=tournament, court=court)
            courts.append(court)

        teams = []
        for team_number in range(1, 11):
            team, _ = Team.objects.get_or_create(
                name=f"Demo Team {team_number:02d}",
                defaults={"pin": f"97{team_number:04d}"[-6:]},
            )
            teams.append(team)
            TournamentTeam.objects.get_or_create(tournament=tournament, team=team)
            for side in range(1, 3):
                player_number = (team_number - 1) * 2 + side
                player, _ = Player.objects.get_or_create(
                    name=f"Demo NPC {player_number:02d}",
                    defaults={"team": team},
                )
                if player.team_id != team.id:
                    player.team = team
                    player.save(update_fields=["team"])
                PlayerCodename.objects.get_or_create(
                    player=player,
                    defaults={"codename": f"DEMO{player_number:02d}"},
                )

        round_obj, _ = Round.objects.get_or_create(
            tournament=tournament,
            number=1,
            defaults={"number_in_stage": 1, "is_complete": False},
        )
        for pair_start in range(0, len(teams), 2):
            Match.objects.get_or_create(
                tournament=tournament,
                round=round_obj,
                team1=teams[pair_start],
                team2=teams[pair_start + 1],
                defaults={"status": "pending"},
            )
        open_round_lineup_window(round_obj.id)
        round_obj.refresh_from_db()

        self.stdout.write(self.style.SUCCESS("Created isolated PFC timed-lineup demo."))
        self.stdout.write(f"tournament_id={tournament.id}")
        self.stdout.write(f"round_id={round_obj.id}")
        self.stdout.write(f"deadline={round_obj.lineup_deadline_at.isoformat()}")
        self.stdout.write("player codenames: DEMO01 through DEMO20")
        self.stdout.write("team PINs: 970001 through 970010")
