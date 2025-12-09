"""
Utility functions for tracking and calculating court complex usage analytics.
"""
import logging
from django.utils import timezone
from django.db.models import Count, Avg, Max, Sum, Q
from datetime import datetime, timedelta, date
from billboard.analytics_models import (
    CourtComplexUsageSnapshot,
    HourlyUsageStats,
    DailyUsageStats,
    UsageAnalyticsSummary
)

logger = logging.getLogger(__name__)


def record_usage_snapshot(court_complex):
    """
    Record a real-time snapshot of current players at a court complex.
    Called when Billboard entries are created or updated.
    
    Args:
        court_complex: CourtComplex object
    """
    from billboard.models import BillboardEntry
    
    try:
        # Count active "AT_COURTS" entries for this complex (last 2 hours)
        current_count = BillboardEntry.objects.filter(
            court_complex=court_complex,
            action_type='AT_COURTS',
            is_active=True,
            created_at__gte=timezone.now() - timedelta(hours=2)
        ).count()
        
        # Create snapshot
        snapshot = CourtComplexUsageSnapshot.objects.create(
            court_complex=court_complex,
            player_count=current_count
        )
        
        logger.info(f"Recorded usage snapshot for {court_complex.name}: {current_count} players")
        return snapshot
        
    except Exception as e:
        logger.error(f"Error recording usage snapshot for {court_complex.name}: {e}")
        return None


def update_hourly_stats(court_complex, target_date=None, target_hour=None):
    """
    Calculate and update hourly statistics for a court complex.
    
    Args:
        court_complex: CourtComplex object
        target_date: Date to calculate stats for (default: today)
        target_hour: Hour to calculate stats for (default: current hour)
    """
    from billboard.models import BillboardEntry
    
    if target_date is None:
        target_date = timezone.now().date()
    if target_hour is None:
        target_hour = timezone.now().hour
    
    try:
        # Get all entries for this hour
        hour_start = datetime.combine(target_date, datetime.min.time().replace(hour=target_hour))
        hour_end = hour_start + timedelta(hours=1)
        
        # Make timezone-aware
        hour_start = timezone.make_aware(hour_start)
        hour_end = timezone.make_aware(hour_end)
        
        entries = BillboardEntry.objects.filter(
            court_complex=court_complex,
            action_type='AT_COURTS',
            created_at__gte=hour_start,
            created_at__lt=hour_end
        )
        
        # Calculate metrics
        unique_visitors = entries.values('codename').distinct().count()
        total_check_ins = entries.count()
        
        # Get peak player count from snapshots
        peak_count = CourtComplexUsageSnapshot.objects.filter(
            court_complex=court_complex,
            timestamp__gte=hour_start,
            timestamp__lt=hour_end
        ).aggregate(Max('player_count'))['player_count__max'] or 0
        
        # Calculate average duration (simplified - time until entry expires or is deactivated)
        # For now, we'll estimate based on entry lifetime
        durations = []
        for entry in entries:
            if not entry.is_active:
                # Entry was deactivated - calculate actual duration
                duration = (entry.updated_at - entry.created_at).total_seconds() / 60
            else:
                # Entry still active - estimate based on current time or 24h limit
                duration = min(
                    (timezone.now() - entry.created_at).total_seconds() / 60,
                    24 * 60  # Max 24 hours
                )
            durations.append(duration)
        
        avg_duration = sum(durations) / len(durations) if durations else None
        
        # Update or create hourly stats
        stats, created = HourlyUsageStats.objects.update_or_create(
            court_complex=court_complex,
            date=target_date,
            hour=target_hour,
            defaults={
                'unique_visitors': unique_visitors,
                'peak_player_count': peak_count,
                'total_check_ins': total_check_ins,
                'average_duration_minutes': avg_duration,
            }
        )
        
        logger.info(f"Updated hourly stats for {court_complex.name} on {target_date} {target_hour}:00 - {unique_visitors} visitors")
        return stats
        
    except Exception as e:
        logger.error(f"Error updating hourly stats for {court_complex.name}: {e}")
        return None


def update_daily_stats(court_complex, target_date=None):
    """
    Calculate and update daily statistics for a court complex.
    Aggregates from hourly stats.
    
    Args:
        court_complex: CourtComplex object
        target_date: Date to calculate stats for (default: today)
    """
    if target_date is None:
        target_date = timezone.now().date()
    
    try:
        # Get all hourly stats for this day
        hourly_stats = HourlyUsageStats.objects.filter(
            court_complex=court_complex,
            date=target_date
        )
        
        if not hourly_stats.exists():
            logger.warning(f"No hourly stats found for {court_complex.name} on {target_date}")
            return None
        
        # Aggregate metrics
        total_unique_visitors = hourly_stats.aggregate(Sum('unique_visitors'))['unique_visitors__sum'] or 0
        total_check_ins = hourly_stats.aggregate(Sum('total_check_ins'))['total_check_ins__sum'] or 0
        peak_count = hourly_stats.aggregate(Max('peak_player_count'))['peak_player_count__max'] or 0
        
        # Find peak hour
        peak_hour_stat = hourly_stats.order_by('-peak_player_count').first()
        peak_hour = peak_hour_stat.hour if peak_hour_stat else None
        
        # Calculate total player-hours (sum of all player counts across hours)
        total_player_hours = sum(
            stat.peak_player_count for stat in hourly_stats
        ) / len(hourly_stats) if hourly_stats else 0
        
        # Average session duration
        avg_durations = [stat.average_duration_minutes for stat in hourly_stats if stat.average_duration_minutes]
        avg_session_duration = sum(avg_durations) / len(avg_durations) if avg_durations else None
        
        # Update or create daily stats
        stats, created = DailyUsageStats.objects.update_or_create(
            court_complex=court_complex,
            date=target_date,
            defaults={
                'unique_visitors': total_unique_visitors,
                'total_check_ins': total_check_ins,
                'peak_hour': peak_hour,
                'peak_player_count': peak_count,
                'total_player_hours': total_player_hours,
                'average_session_duration_minutes': avg_session_duration,
            }
        )
        
        logger.info(f"Updated daily stats for {court_complex.name} on {target_date} - {total_unique_visitors} visitors")
        return stats
        
    except Exception as e:
        logger.error(f"Error updating daily stats for {court_complex.name}: {e}")
        return None


def get_current_occupancy(court_complex):
    """
    Get current number of players at a court complex.
    
    Args:
        court_complex: CourtComplex object
        
    Returns:
        int: Number of active players
    """
    from billboard.models import BillboardEntry
    
    return BillboardEntry.objects.filter(
        court_complex=court_complex,
        action_type='AT_COURTS',
        is_active=True,
        created_at__gte=timezone.now() - timedelta(hours=2)
    ).count()


def get_peak_hours(court_complex, days=7):
    """
    Get peak hours for a court complex over the last N days.
    
    Args:
        court_complex: CourtComplex object
        days: Number of days to analyze
        
    Returns:
        list: List of (hour, avg_visitors) tuples sorted by visitors
    """
    start_date = timezone.now().date() - timedelta(days=days)
    
    hourly_stats = HourlyUsageStats.objects.filter(
        court_complex=court_complex,
        date__gte=start_date
    ).values('hour').annotate(
        avg_visitors=Avg('unique_visitors'),
        avg_peak=Avg('peak_player_count')
    ).order_by('-avg_peak')
    
    return [(stat['hour'], stat['avg_peak']) for stat in hourly_stats]


def get_busiest_days(court_complex, weeks=4):
    """
    Get busiest days of the week for a court complex.
    
    Args:
        court_complex: CourtComplex object
        weeks: Number of weeks to analyze
        
    Returns:
        dict: Day of week (0=Monday) to average visitors
    """
    start_date = timezone.now().date() - timedelta(weeks=weeks * 7)
    
    daily_stats = DailyUsageStats.objects.filter(
        court_complex=court_complex,
        date__gte=start_date
    )
    
    # Group by day of week
    day_averages = {}
    for day in range(7):  # 0=Monday, 6=Sunday
        day_stats = [stat for stat in daily_stats if stat.date.weekday() == day]
        if day_stats:
            avg = sum(stat.unique_visitors for stat in day_stats) / len(day_stats)
            day_averages[day] = avg
    
    return day_averages


def trigger_analytics_update(court_complex):
    """
    Trigger all analytics updates for a court complex.
    Called when Billboard entries are created/updated.
    
    Args:
        court_complex: CourtComplex object
    """
    try:
        # Record snapshot
        record_usage_snapshot(court_complex)
        
        # Update current hour stats
        update_hourly_stats(court_complex)
        
        # Update today's daily stats
        update_daily_stats(court_complex)
        
        logger.info(f"Triggered analytics update for {court_complex.name}")
        
    except Exception as e:
        logger.error(f"Error triggering analytics update for {court_complex.name}: {e}")
