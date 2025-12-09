"""
Analytics models for tracking court complex usage patterns.
"""
from django.db import models
from django.utils import timezone
from courts.models import CourtComplex


class CourtComplexUsageSnapshot(models.Model):
    """
    Real-time snapshots of court complex usage.
    Captures player count at specific moments.
    """
    court_complex = models.ForeignKey(
        CourtComplex,
        on_delete=models.CASCADE,
        related_name='usage_snapshots'
    )
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    player_count = models.IntegerField(default=0)
    
    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['court_complex', '-timestamp']),
            models.Index(fields=['timestamp']),
        ]
    
    def __str__(self):
        return f"{self.court_complex.name} - {self.player_count} players at {self.timestamp}"


class HourlyUsageStats(models.Model):
    """
    Aggregated hourly statistics for court complex usage.
    One record per court complex per hour.
    """
    court_complex = models.ForeignKey(
        CourtComplex,
        on_delete=models.CASCADE,
        related_name='hourly_stats'
    )
    date = models.DateField(db_index=True)
    hour = models.IntegerField()  # 0-23
    
    # Metrics
    unique_visitors = models.IntegerField(default=0)
    peak_player_count = models.IntegerField(default=0)
    total_check_ins = models.IntegerField(default=0)
    average_duration_minutes = models.FloatField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-date', '-hour']
        unique_together = ['court_complex', 'date', 'hour']
        indexes = [
            models.Index(fields=['court_complex', '-date', '-hour']),
            models.Index(fields=['date', 'hour']),
        ]
    
    def __str__(self):
        return f"{self.court_complex.name} - {self.date} {self.hour}:00 - {self.unique_visitors} visitors"


class DailyUsageStats(models.Model):
    """
    Aggregated daily statistics for court complex usage.
    One record per court complex per day.
    """
    court_complex = models.ForeignKey(
        CourtComplex,
        on_delete=models.CASCADE,
        related_name='daily_stats'
    )
    date = models.DateField(db_index=True)
    
    # Metrics
    unique_visitors = models.IntegerField(default=0)
    total_check_ins = models.IntegerField(default=0)
    peak_hour = models.IntegerField(null=True, blank=True)  # 0-23
    peak_player_count = models.IntegerField(default=0)
    total_player_hours = models.FloatField(default=0.0)
    average_session_duration_minutes = models.FloatField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-date']
        unique_together = ['court_complex', 'date']
        indexes = [
            models.Index(fields=['court_complex', '-date']),
            models.Index(fields=['date']),
        ]
    
    def __str__(self):
        return f"{self.court_complex.name} - {self.date} - {self.unique_visitors} visitors"


class UsageAnalyticsSummary(models.Model):
    """
    Summary statistics for a court complex over a time period.
    Used for quick access to common metrics.
    """
    court_complex = models.ForeignKey(
        CourtComplex,
        on_delete=models.CASCADE,
        related_name='analytics_summaries'
    )
    period_type = models.CharField(
        max_length=20,
        choices=[
            ('week', 'Weekly'),
            ('month', 'Monthly'),
            ('year', 'Yearly'),
            ('all_time', 'All Time'),
        ]
    )
    period_start = models.DateField()
    period_end = models.DateField()
    
    # Metrics
    total_unique_visitors = models.IntegerField(default=0)
    total_check_ins = models.IntegerField(default=0)
    average_daily_visitors = models.FloatField(default=0.0)
    busiest_day_of_week = models.IntegerField(null=True, blank=True)  # 0=Monday, 6=Sunday
    busiest_hour = models.IntegerField(null=True, blank=True)  # 0-23
    total_player_hours = models.FloatField(default=0.0)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-period_end']
        unique_together = ['court_complex', 'period_type', 'period_start']
        indexes = [
            models.Index(fields=['court_complex', 'period_type', '-period_end']),
        ]
    
    def __str__(self):
        return f"{self.court_complex.name} - {self.period_type} ({self.period_start} to {self.period_end})"
