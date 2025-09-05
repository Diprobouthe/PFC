from django.core.management.base import BaseCommand
from signin.models import TeamTournamentSignin
from tournaments.models import TournamentTeam
from django.utils import timezone

class Command(BaseCommand):
    help = 'Synchronizes TeamTournamentSignin records with TournamentTeam records'

    def handle(self, *args, **options):
        # Get all active team sign-ins
        active_signins = TeamTournamentSignin.objects.filter(is_active=True)
        created_count = 0
        
        for signin in active_signins:
            # Create corresponding TournamentTeam record if it doesn't exist
            tournament_team, created = TournamentTeam.objects.get_or_create(
                team=signin.team,
                tournament=signin.tournament,
                defaults={'registration_date': signin.signed_in_at or timezone.now()}
            )
            
            if created:
                created_count += 1
                self.stdout.write(f"Created TournamentTeam record for {signin.team.name} in {signin.tournament.name}")
        
        self.stdout.write(self.style.SUCCESS(f'Successfully synchronized {active_signins.count()} team sign-ins, created {created_count} new TournamentTeam records'))
