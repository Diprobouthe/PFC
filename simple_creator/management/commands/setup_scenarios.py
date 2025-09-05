from django.core.management.base import BaseCommand
from simple_creator.models import TournamentScenario, VoucherCode
import random
import string


class Command(BaseCommand):
    help = 'Setup initial tournament scenarios (Fair and Madness)'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--create-vouchers',
            type=int,
            default=0,
            help='Number of Madness vouchers to create'
        )
    
    def handle(self, *args, **options):
        self.stdout.write('Setting up initial tournament scenarios...')
        
        # Create Fair scenario (free)
        fair_scenario, created = TournamentScenario.objects.get_or_create(
            name='fair',
            defaults={
                'display_name': 'Fair',
                'description': 'A balanced tournament with 3 Swiss rounds using balance draft for fair team distribution.',
                'is_free': True,
                'requires_voucher': False,
                'max_doubles_players': 12,
                'max_triples_players': 18,
                'tournament_type': 'swiss',
                'num_rounds': 3,
                'matches_per_team': 3,
                'draft_type': 'balance'
            }
        )
        
        if created:
            self.stdout.write(
                self.style.SUCCESS(f'✅ Created Fair scenario')
            )
        else:
            self.stdout.write(f'ℹ️  Fair scenario already exists')
        
        # Create Madness scenario (requires voucher)
        madness_scenario, created = TournamentScenario.objects.get_or_create(
            name='madness',
            defaults={
                'display_name': 'Madness',
                'description': 'An exciting tournament with 3 games per team using partial round robin and snake draft for unpredictable matchups.',
                'is_free': False,
                'requires_voucher': True,
                'max_doubles_players': 12,
                'max_triples_players': 18,
                'tournament_type': 'partial_robin',
                'num_rounds': 3,
                'matches_per_team': 3,
                'draft_type': 'snake'
            }
        )
        
        if created:
            self.stdout.write(
                self.style.SUCCESS(f'✅ Created Madness scenario')
            )
        else:
            self.stdout.write(f'ℹ️  Madness scenario already exists')
        
        # Create vouchers if requested
        voucher_count = options['create_vouchers']
        if voucher_count > 0:
            self.stdout.write(f'Creating {voucher_count} Madness vouchers...')
            
            for i in range(voucher_count):
                # Generate random voucher code
                code = 'MAD' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
                
                voucher = VoucherCode.objects.create(
                    code=code,
                    scenario=madness_scenario
                )
                
                self.stdout.write(f'  ✅ Created voucher: {code}')
        
        self.stdout.write(
            self.style.SUCCESS(
                f'\n🎉 Setup complete! Available scenarios:\n'
                f'  • Fair (Free): 3 Swiss rounds, balance draft\n'
                f'  • Madness (Voucher): 3 games per team, snake draft\n'
            )
        )

