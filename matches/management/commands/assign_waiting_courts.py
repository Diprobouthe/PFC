from django.core.management.base import BaseCommand
from matches.models import Match
from courts.views import auto_assign_court
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

class Command(BaseCommand):
    help = 'Assign courts to matches that are waiting for courts'

    def handle(self, *args, **options):
        # Find all matches waiting for courts
        waiting_matches = Match.objects.filter(
            status="pending_verification",
            waiting_for_court=True
        ).order_by("created_at")
        
        if not waiting_matches.exists():
            self.stdout.write(self.style.SUCCESS('No matches waiting for courts.'))
            return
        
        assigned_count = 0
        
        for match in waiting_matches:
            self.stdout.write(f'Checking match {match.id}: {match.team1} vs {match.team2}')
            
            # Try to assign a court
            court = auto_assign_court(match)
            
            if court:
                # Court assigned - activate the match
                match.status = "active"
                match.start_time = timezone.now()
                match.waiting_for_court = False
                match.save()
                
                assigned_count += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f'✅ Assigned Court {court.number} to match {match.id} and activated it'
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f'⏳ No available court for match {match.id}'
                    )
                )
        
        if assigned_count > 0:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully assigned courts to {assigned_count} waiting matches.'
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING('No courts could be assigned to waiting matches.')
            )

