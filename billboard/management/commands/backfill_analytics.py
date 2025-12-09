"""
Management command to backfill analytics data from existing Billboard entries.
Usage: python manage.py backfill_analytics [--days N] [--complex-id ID]
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta, datetime
from billboard.models import BillboardEntry
from billboard.analytics_utils import (
    record_usage_snapshot,
    update_hourly_stats,
    update_daily_stats
)
from courts.models import CourtComplex


class Command(BaseCommand):
    help = 'Backfill analytics data from existing Billboard entries'

    def add_arguments(self, parser):
        parser.add_argument(
            '--days',
            type=int,
            default=30,
            help='Number of days to backfill (default: 30)'
        )
        parser.add_argument(
            '--complex-id',
            type=int,
            help='Specific court complex ID to backfill (optional)'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force recalculation even if stats already exist'
        )

    def handle(self, *args, **options):
        days = options['days']
        complex_id = options['complex_id']
        force = options['force']
        
        self.stdout.write(self.style.SUCCESS(f'Starting analytics backfill for last {days} days...'))
        
        # Get court complexes to process
        if complex_id:
            complexes = CourtComplex.objects.filter(id=complex_id)
            if not complexes.exists():
                self.stdout.write(self.style.ERROR(f'Court complex with ID {complex_id} not found'))
                return
        else:
            complexes = CourtComplex.objects.all()
        
        # Calculate date range
        end_date = timezone.now().date()
        start_date = end_date - timedelta(days=days)
        
        self.stdout.write(f'Processing {complexes.count()} court complex(es) from {start_date} to {end_date}')
        
        total_hourly = 0
        total_daily = 0
        
        # Process each court complex
        for complex in complexes:
            self.stdout.write(f'\nProcessing: {complex.name}')
            
            # Check if there are any entries for this complex
            entry_count = BillboardEntry.objects.filter(
                court_complex=complex,
                action_type='AT_COURTS',
                created_at__date__gte=start_date,
                created_at__date__lte=end_date
            ).count()
            
            if entry_count == 0:
                self.stdout.write(self.style.WARNING(f'  No entries found for {complex.name}'))
                continue
            
            self.stdout.write(f'  Found {entry_count} entries')
            
            # Process each day
            current_date = start_date
            while current_date <= end_date:
                # Process each hour of the day
                for hour in range(24):
                    try:
                        stats = update_hourly_stats(complex, current_date, hour)
                        if stats:
                            total_hourly += 1
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f'  Error processing {current_date} {hour}:00 - {e}'))
                
                # Process daily stats
                try:
                    stats = update_daily_stats(complex, current_date)
                    if stats:
                        total_daily += 1
                        self.stdout.write(f'  ✓ {current_date}: {stats.unique_visitors} visitors')
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f'  Error processing daily stats for {current_date} - {e}'))
                
                current_date += timedelta(days=1)
        
        self.stdout.write(self.style.SUCCESS(f'\n✅ Backfill complete!'))
        self.stdout.write(f'  Hourly stats created/updated: {total_hourly}')
        self.stdout.write(f'  Daily stats created/updated: {total_daily}')
