"""
Management command to show shot tracker statistics.

Usage:
    python manage.py shot_tracker_stats
    python manage.py shot_tracker_stats --user username
    python manage.py shot_tracker_stats --detailed
"""

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db.models import Count, Sum, Avg, Max
from django.utils import timezone
from datetime import timedelta

from shooting.models import ShotSession, ShotEvent, Achievement, EarnedAchievement


class Command(BaseCommand):
    help = 'Show shot tracker statistics'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--user',
            type=str,
            help='Show stats for specific user (username)',
        )
        
        parser.add_argument(
            '--detailed',
            action='store_true',
            help='Show detailed statistics',
        )
        
        parser.add_argument(
            '--recent-days',
            type=int,
            default=7,
            help='Show stats for recent N days (default: 7)',
        )
    
    def handle(self, *args, **options):
        user_filter = options['user']
        detailed = options['detailed']
        recent_days = options['recent_days']
        
        self.stdout.write(
            self.style.SUCCESS("Shot Tracker Statistics")
        )
        self.stdout.write("=" * 50)
        
        if user_filter:
            try:
                user = User.objects.get(username=user_filter)
                self.show_user_stats(user, detailed, recent_days)
            except User.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f"User '{user_filter}' not found")
                )
        else:
            self.show_global_stats(detailed, recent_days)
    
    def show_global_stats(self, detailed, recent_days):
        """Show global shot tracker statistics"""
        
        # Basic counts
        total_users = User.objects.filter(shot_sessions__isnull=False).distinct().count()
        total_sessions = ShotSession.objects.count()
        active_sessions = ShotSession.objects.filter(is_active=True).count()
        total_events = ShotEvent.objects.count()
        
        self.stdout.write(f"Total Users with Sessions: {total_users}")
        self.stdout.write(f"Total Sessions: {total_sessions}")
        self.stdout.write(f"Active Sessions: {active_sessions}")
        self.stdout.write(f"Total Shot Events: {total_events}")
        self.stdout.write("")
        
        # Recent activity
        recent_cutoff = timezone.now() - timedelta(days=recent_days)
        recent_sessions = ShotSession.objects.filter(started_at__gte=recent_cutoff)
        recent_events = ShotEvent.objects.filter(timestamp__gte=recent_cutoff)
        
        self.stdout.write(f"Recent Activity (last {recent_days} days):")
        self.stdout.write(f"  New Sessions: {recent_sessions.count()}")
        self.stdout.write(f"  Shot Events: {recent_events.count()}")
        self.stdout.write("")
        
        # Session statistics
        session_stats = ShotSession.objects.aggregate(
            avg_shots=Avg('total_shots'),
            avg_hits=Avg('total_hits'),
            max_streak=Max('best_streak'),
            total_shots=Sum('total_shots'),
            total_hits=Sum('total_hits')
        )
        
        if session_stats['total_shots']:
            global_hit_rate = session_stats['total_hits'] / session_stats['total_shots']
            
            self.stdout.write("Global Statistics:")
            self.stdout.write(f"  Total Shots Taken: {session_stats['total_shots']}")
            self.stdout.write(f"  Total Hits: {session_stats['total_hits']}")
            self.stdout.write(f"  Global Hit Rate: {global_hit_rate:.1%}")
            self.stdout.write(f"  Average Shots per Session: {session_stats['avg_shots']:.1f}")
            self.stdout.write(f"  Best Streak Ever: {session_stats['max_streak']}")
            self.stdout.write("")
        
        # Mode distribution
        mode_stats = ShotSession.objects.values('mode').annotate(
            count=Count('id'),
            total_shots=Sum('total_shots')
        ).order_by('-count')
        
        self.stdout.write("Sessions by Mode:")
        for mode_stat in mode_stats:
            self.stdout.write(
                f"  {mode_stat['mode']}: {mode_stat['count']} sessions, "
                f"{mode_stat['total_shots'] or 0} shots"
            )
        self.stdout.write("")
        
        # Achievement statistics
        total_achievements = Achievement.objects.filter(is_active=True).count()
        earned_achievements = EarnedAchievement.objects.count()
        users_with_achievements = User.objects.filter(
            earned_achievements__isnull=False
        ).distinct().count()
        
        self.stdout.write("Achievement Statistics:")
        self.stdout.write(f"  Available Achievements: {total_achievements}")
        self.stdout.write(f"  Total Earned: {earned_achievements}")
        self.stdout.write(f"  Users with Achievements: {users_with_achievements}")
        
        if detailed:
            self.show_detailed_global_stats()
    
    def show_user_stats(self, user, detailed, recent_days):
        """Show statistics for a specific user"""
        
        self.stdout.write(f"Statistics for User: {user.username}")
        self.stdout.write("-" * 30)
        
        # User sessions
        sessions = ShotSession.objects.filter(user=user)
        active_sessions = sessions.filter(is_active=True)
        
        if not sessions.exists():
            self.stdout.write("No sessions found for this user.")
            return
        
        # Basic stats
        session_stats = sessions.aggregate(
            total_sessions=Count('id'),
            total_shots=Sum('total_shots'),
            total_hits=Sum('total_hits'),
            best_streak=Max('best_streak'),
            avg_shots=Avg('total_shots')
        )
        
        hit_rate = 0
        if session_stats['total_shots']:
            hit_rate = session_stats['total_hits'] / session_stats['total_shots']
        
        self.stdout.write(f"Total Sessions: {session_stats['total_sessions']}")
        self.stdout.write(f"Active Sessions: {active_sessions.count()}")
        self.stdout.write(f"Total Shots: {session_stats['total_shots'] or 0}")
        self.stdout.write(f"Total Hits: {session_stats['total_hits'] or 0}")
        self.stdout.write(f"Hit Rate: {hit_rate:.1%}")
        self.stdout.write(f"Best Streak: {session_stats['best_streak'] or 0}")
        self.stdout.write(f"Avg Shots/Session: {session_stats['avg_shots'] or 0:.1f}")
        self.stdout.write("")
        
        # Recent activity
        recent_cutoff = timezone.now() - timedelta(days=recent_days)
        recent_sessions = sessions.filter(started_at__gte=recent_cutoff)
        
        self.stdout.write(f"Recent Activity (last {recent_days} days):")
        self.stdout.write(f"  Sessions: {recent_sessions.count()}")
        
        if recent_sessions.exists():
            recent_stats = recent_sessions.aggregate(
                shots=Sum('total_shots'),
                hits=Sum('total_hits')
            )
            recent_hit_rate = 0
            if recent_stats['shots']:
                recent_hit_rate = recent_stats['hits'] / recent_stats['shots']
            
            self.stdout.write(f"  Shots: {recent_stats['shots'] or 0}")
            self.stdout.write(f"  Hit Rate: {recent_hit_rate:.1%}")
        
        self.stdout.write("")
        
        # Achievements
        achievements = EarnedAchievement.objects.filter(user=user).select_related('achievement')
        self.stdout.write(f"Achievements Earned: {achievements.count()}")
        
        if achievements.exists():
            for earned in achievements.order_by('-earned_at')[:5]:
                self.stdout.write(f"  {earned.achievement.name} - {earned.earned_at.date()}")
        
        if detailed:
            self.show_detailed_user_stats(user)
    
    def show_detailed_global_stats(self):
        """Show detailed global statistics"""
        
        self.stdout.write("\nDetailed Statistics:")
        self.stdout.write("-" * 20)
        
        # Top performers
        top_users = User.objects.annotate(
            total_shots=Sum('shot_sessions__total_shots'),
            total_hits=Sum('shot_sessions__total_hits'),
            best_streak=Max('shot_sessions__best_streak')
        ).filter(total_shots__gt=0).order_by('-total_shots')[:5]
        
        self.stdout.write("Top Shooters (by total shots):")
        for i, user in enumerate(top_users, 1):
            hit_rate = user.total_hits / user.total_shots if user.total_shots else 0
            self.stdout.write(
                f"  {i}. {user.username}: {user.total_shots} shots, "
                f"{hit_rate:.1%} hit rate, best streak {user.best_streak or 0}"
            )
        
        self.stdout.write("")
        
        # Achievement leaderboard
        achievement_leaders = User.objects.annotate(
            achievement_count=Count('earned_achievements')
        ).filter(achievement_count__gt=0).order_by('-achievement_count')[:5]
        
        self.stdout.write("Achievement Leaders:")
        for i, user in enumerate(achievement_leaders, 1):
            self.stdout.write(
                f"  {i}. {user.username}: {user.achievement_count} achievements"
            )
    
    def show_detailed_user_stats(self, user):
        """Show detailed statistics for a user"""
        
        self.stdout.write(f"\nDetailed Stats for {user.username}:")
        self.stdout.write("-" * 30)
        
        # Recent sessions
        recent_sessions = ShotSession.objects.filter(user=user).order_by('-started_at')[:5]
        
        self.stdout.write("Recent Sessions:")
        for session in recent_sessions:
            hit_rate = session.hit_rate if session.total_shots > 0 else 0
            status = "Active" if session.is_active else "Ended"
            self.stdout.write(
                f"  {session.started_at.date()} ({session.mode}): "
                f"{session.total_hits}/{session.total_shots} ({hit_rate:.1%}) - {status}"
            )
        
        self.stdout.write("")
        
        # Mode preferences
        mode_stats = ShotSession.objects.filter(user=user).values('mode').annotate(
            count=Count('id'),
            total_shots=Sum('total_shots')
        ).order_by('-count')
        
        self.stdout.write("Session Modes:")
        for mode_stat in mode_stats:
            self.stdout.write(
                f"  {mode_stat['mode']}: {mode_stat['count']} sessions, "
                f"{mode_stat['total_shots'] or 0} shots"
            )
