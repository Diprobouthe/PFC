from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from tournaments.models import Tournament
from matches.models import Match
from teams.models import Team
from courts.models import Court
from signin.models import TeamTournamentSignin

class Command(BaseCommand):
    help = 'Create user groups and assign permissions for the PFC platform'

    def handle(self, *args, **options):
        # Create groups
        admin_group, created = Group.objects.get_or_create(name='Tournament Administrators')
        staff_group, created = Group.objects.get_or_create(name='Tournament Staff')
        team_group, created = Group.objects.get_or_create(name='Team Members')
        
        self.stdout.write(self.style.SUCCESS('Created user groups'))
        
        # Get content types
        tournament_ct = ContentType.objects.get_for_model(Tournament)
        match_ct = ContentType.objects.get_for_model(Match)
        team_ct = ContentType.objects.get_for_model(Team)
        court_ct = ContentType.objects.get_for_model(Court)
        signin_ct = ContentType.objects.get_for_model(TeamTournamentSignin)
        
        # Clear existing permissions for these groups
        admin_group.permissions.clear()
        staff_group.permissions.clear()
        team_group.permissions.clear()
        
        # Assign permissions to Tournament Administrators
        admin_permissions = Permission.objects.filter(
            content_type__in=[tournament_ct, match_ct, team_ct, court_ct, signin_ct]
        )
        admin_group.permissions.add(*admin_permissions)
        
        # Assign permissions to Tournament Staff
        staff_permissions = Permission.objects.filter(
            content_type__in=[match_ct, court_ct, signin_ct]
        ).exclude(codename__startswith='delete_')
        
        # Add view permissions for tournaments and teams
        staff_permissions |= Permission.objects.filter(
            content_type__in=[tournament_ct, team_ct],
            codename__startswith='view_'
        )
        
        staff_group.permissions.add(*staff_permissions)
        
        # Assign permissions to Team Members
        team_permissions = Permission.objects.filter(
            content_type__in=[match_ct, signin_ct],
            codename__in=['view_match', 'view_teamtournamentsignin', 'add_teamtournamentsignin']
        )
        
        # Add view permissions for tournaments and teams
        team_permissions |= Permission.objects.filter(
            content_type__in=[tournament_ct, team_ct],
            codename__startswith='view_'
        )
        
        team_group.permissions.add(*team_permissions)
        
        self.stdout.write(self.style.SUCCESS('Assigned permissions to user groups'))
        
        self.stdout.write(self.style.SUCCESS(
            f'Tournament Administrators: {admin_group.permissions.count()} permissions\n'
            f'Tournament Staff: {staff_group.permissions.count()} permissions\n'
            f'Team Members: {team_group.permissions.count()} permissions'
        ))
