from django.core.management.base import BaseCommand
from django.utils import timezone
from tournaments.models import Tournament, TournamentTeam, Round
from teams.models import Team, Player
from matches.models import Match, MatchResult
from leaderboards.models import Leaderboard
from leaderboards.views import update_tournament_leaderboard
import random
from datetime import timedelta

class Command(BaseCommand):
    help = 'Creates test data for the Petanque Platform'

    def handle(self, *args, **options):
        self.stdout.write('Creating test data for Petanque Platform...')
        
        # Create teams
        self.create_teams()
        
        # Create tournaments
        self.create_tournaments()
        
        # Create matches
        self.create_matches()
        
        # Update leaderboards
        self.update_leaderboards()
        
        self.stdout.write(self.style.SUCCESS('Successfully created test data!'))
    
    def create_teams(self):
        self.stdout.write('Creating teams...')
        
        team_data = [
            {
                'name': 'Team Alpha',
                'contact_name': 'John Smith',
                'contact_email': 'john@example.com',
                'contact_phone': '555-123-4567',
                'pin': '1234',
                'players': [
                    {'name': 'Alex Johnson', 'position': 'Pointer', 'experience_level': 'expert'},
                    {'name': 'Sarah Williams', 'position': 'Shooter', 'experience_level': 'advanced'},
                    {'name': 'Mike Davis', 'position': 'Middle', 'experience_level': 'intermediate'},
                ]
            },
            {
                'name': 'Team Beta',
                'contact_name': 'Jane Doe',
                'contact_email': 'jane@example.com',
                'contact_phone': '555-987-6543',
                'pin': '2345',
                'players': [
                    {'name': 'Robert Brown', 'position': 'Pointer', 'experience_level': 'advanced'},
                    {'name': 'Emily Wilson', 'position': 'Shooter', 'experience_level': 'expert'},
                    {'name': 'David Miller', 'position': 'Middle', 'experience_level': 'advanced'},
                ]
            },
            {
                'name': 'Team Gamma',
                'contact_name': 'Michael Johnson',
                'contact_email': 'michael@example.com',
                'contact_phone': '555-456-7890',
                'pin': '3456',
                'players': [
                    {'name': 'Lisa Taylor', 'position': 'Pointer', 'experience_level': 'intermediate'},
                    {'name': 'James Anderson', 'position': 'Shooter', 'experience_level': 'advanced'},
                    {'name': 'Karen Thomas', 'position': 'Middle', 'experience_level': 'beginner'},
                ]
            },
            {
                'name': 'Team Delta',
                'contact_name': 'Susan Wilson',
                'contact_email': 'susan@example.com',
                'contact_phone': '555-789-0123',
                'pin': '4567',
                'players': [
                    {'name': 'Thomas White', 'position': 'Pointer', 'experience_level': 'advanced'},
                    {'name': 'Jennifer Lee', 'position': 'Shooter', 'experience_level': 'intermediate'},
                    {'name': 'Richard Clark', 'position': 'Middle', 'experience_level': 'advanced'},
                ]
            },
            {
                'name': 'Team Epsilon',
                'contact_name': 'Robert Martin',
                'contact_email': 'robert@example.com',
                'contact_phone': '555-321-6547',
                'pin': '5678',
                'players': [
                    {'name': 'Patricia Moore', 'position': 'Pointer', 'experience_level': 'expert'},
                    {'name': 'Charles Jackson', 'position': 'Shooter', 'experience_level': 'advanced'},
                    {'name': 'Elizabeth Harris', 'position': 'Middle', 'experience_level': 'intermediate'},
                ]
            },
            {
                'name': 'Team Zeta',
                'contact_name': 'William Brown',
                'contact_email': 'william@example.com',
                'contact_phone': '555-654-3210',
                'pin': '6789',
                'players': [
                    {'name': 'Barbara Lewis', 'position': 'Pointer', 'experience_level': 'intermediate'},
                    {'name': 'Joseph Martin', 'position': 'Shooter', 'experience_level': 'beginner'},
                    {'name': 'Dorothy Wilson', 'position': 'Middle', 'experience_level': 'advanced'},
                ]
            },
        ]
        
        for team_info in team_data:
            team = Team.objects.create(
                name=team_info['name'],
                contact_name=team_info['contact_name'],
                contact_email=team_info['contact_email'],
                contact_phone=team_info['contact_phone'],
                pin=team_info['pin']
            )
            
            for player_info in team_info['players']:
                Player.objects.create(
                    team=team,
                    name=player_info['name'],
                    position=player_info['position'],
                    experience_level=player_info['experience_level']
                )
            
            self.stdout.write(f'Created team: {team.name} with {team.players.count()} players')
    
    def create_tournaments(self):
        self.stdout.write('Creating tournaments...')
        
        tournament_data = [
            {
                'name': 'Spring Championship 2025',
                'format': 'round_robin',
                'location': 'Central Park',
                'start_date': timezone.now() - timedelta(days=30),
                'end_date': timezone.now() + timedelta(days=30),
                'is_active': True,
                'is_archived': False,
                'teams': ['Team Alpha', 'Team Beta', 'Team Gamma', 'Team Delta']
            },
            {
                'name': 'Winter Cup 2025',
                'format': 'knockout',
                'location': 'Indoor Sports Center',
                'start_date': timezone.now() - timedelta(days=60),
                'end_date': timezone.now() - timedelta(days=30),
                'is_active': False,
                'is_archived': True,
                'teams': ['Team Alpha', 'Team Beta', 'Team Epsilon', 'Team Zeta']
            },
            {
                'name': 'Regional Qualifier 2025',
                'format': 'swiss',
                'location': 'Community Center',
                'start_date': timezone.now() - timedelta(days=15),
                'end_date': timezone.now() + timedelta(days=45),
                'is_active': True,
                'is_archived': False,
                'teams': ['Team Gamma', 'Team Delta', 'Team Epsilon', 'Team Zeta']
            },
        ]
        
        for tournament_info in tournament_data:
            tournament = Tournament.objects.create(
                name=tournament_info['name'],
                format=tournament_info['format'],
                location=tournament_info['location'],
                start_date=tournament_info['start_date'],
                end_date=tournament_info['end_date'],
                is_active=tournament_info['is_active'],
                is_archived=tournament_info['is_archived']
            )
            
            # Assign teams to tournament
            for team_name in tournament_info['teams']:
                team = Team.objects.get(name=team_name)
                TournamentTeam.objects.create(
                    tournament=tournament,
                    team=team
                )
            
            self.stdout.write(f'Created tournament: {tournament.name} with {tournament.teams.count()} teams')
    
    def create_matches(self):
        self.stdout.write('Creating matches...')
        
        # Get all tournaments
        tournaments = Tournament.objects.all()
        
        for tournament in tournaments:
            # Create rounds
            if tournament.format == 'round_robin':
                num_rounds = tournament.teams.count() - 1
            elif tournament.format == 'knockout':
                num_rounds = 2  # Simplified for test data
            else:  # swiss
                num_rounds = 3  # Simplified for test data
            
            for round_num in range(1, num_rounds + 1):
                round_obj, _ = Round.objects.get_or_create(
                    tournament=tournament,
                    number=round_num
                )
            
            # Get teams in this tournament
            teams = list(tournament.teams.all())
            
            # Create matches
            if len(teams) >= 2:
                # Create completed matches
                team1 = teams[0]
                team2 = teams[1]
                
                match = Match.objects.create(
                    tournament=tournament,
                    round=Round.objects.get(tournament=tournament, number=1),
                    team1=team1,
                    team2=team2,
                    status='completed',
                    team1_score=13,
                    team2_score=8,
                    start_time=timezone.now() - timedelta(days=10, hours=2),
                    end_time=timezone.now() - timedelta(days=10)
                )
                
                # Create match result
                MatchResult.objects.create(
                    match=match,
                    submitted_by=team1,
                    validated_by=team2,
                    submitted_at=match.end_time,
                    validated_at=match.end_time + timedelta(minutes=10),
                    notes="Great match!"
                )
                
                self.stdout.write(f'Created completed match: {team1.name} vs {team2.name}')
            
            if len(teams) >= 4:
                # Create active match
                team3 = teams[2]
                team4 = teams[3]
                
                match = Match.objects.create(
                    tournament=tournament,
                    round=Round.objects.get(tournament=tournament, number=1),
                    team1=team3,
                    team2=team4,
                    status='active',
                    start_time=timezone.now() - timedelta(hours=1)
                )
                
                self.stdout.write(f'Created active match: {team3.name} vs {team4.name}')
            
            if len(teams) >= 6:
                # Create pending match
                team5 = teams[4]
                team6 = teams[5]
                
                match = Match.objects.create(
                    tournament=tournament,
                    round=Round.objects.get(tournament=tournament, number=2),
                    team1=team5,
                    team2=team6,
                    status='pending'
                )
                
                self.stdout.write(f'Created pending match: {team5.name} vs {team6.name}')
    
    def update_leaderboards(self):
        self.stdout.write('Updating leaderboards...')
        
        # Get all tournaments
        tournaments = Tournament.objects.all()
        
        for tournament in tournaments:
            # Create or get leaderboard
            leaderboard, _ = Leaderboard.objects.get_or_create(tournament=tournament)
            
            # Update leaderboard
            update_tournament_leaderboard(tournament)
            
            self.stdout.write(f'Updated leaderboard for tournament: {tournament.name}')
