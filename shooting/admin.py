"""
Admin configuration for Shot Accuracy Tracker
"""

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import ShotSession, ShotEvent, Achievement, EarnedAchievement


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'threshold', 'color_preview', 'is_active', 'earned_count']
    list_filter = ['is_active', 'threshold']
    search_fields = ['code', 'name']
    ordering = ['threshold', 'code']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('code', 'name', 'description', 'threshold')
        }),
        ('Display Options', {
            'fields': ('icon', 'color', 'is_active')
        }),
    )
    
    def color_preview(self, obj):
        return format_html(
            '<span style="background-color: {}; padding: 2px 8px; border-radius: 3px; color: white;">{}</span>',
            obj.color,
            obj.color
        )
    color_preview.short_description = 'Color'
    
    def earned_count(self, obj):
        count = obj.earned_by.count()
        return format_html('<strong>{}</strong>', count)
    earned_count.short_description = 'Times Earned'


class ShotEventInline(admin.TabularInline):
    model = ShotEvent
    extra = 0
    readonly_fields = ['idx', 'timestamp']
    ordering = ['idx']
    
    def has_add_permission(self, request, obj=None):
        return False  # Prevent manual event creation


class EarnedAchievementInline(admin.TabularInline):
    model = EarnedAchievement
    extra = 0
    readonly_fields = ['achievement', 'earned_at']
    
    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ShotSession)
class ShotSessionAdmin(admin.ModelAdmin):
    list_display = [
        'id_short', 'user', 'mode', 'match_link', 'stats_summary', 
        'is_active', 'started_at', 'duration'
    ]
    list_filter = ['mode', 'is_active', 'started_at']
    search_fields = ['user__username', 'match_id']
    readonly_fields = [
        'id', 'started_at', 'total_shots', 'total_hits', 
        'current_streak', 'best_streak', 'hit_rate_display'
    ]
    ordering = ['-started_at']
    
    fieldsets = (
        ('Session Info', {
            'fields': ('id', 'user', 'mode', 'match_id', 'inning')
        }),
        ('Timing', {
            'fields': ('started_at', 'ended_at', 'is_active')
        }),
        ('Statistics', {
            'fields': ('total_shots', 'total_hits', 'hit_rate_display', 'current_streak', 'best_streak')
        }),
    )
    
    inlines = [ShotEventInline, EarnedAchievementInline]
    
    def id_short(self, obj):
        return str(obj.id)[:8] + "..."
    id_short.short_description = 'ID'
    
    def match_link(self, obj):
        if obj.match_id:
            return format_html(
                '<a href="/admin/matches/match/?q={}" target="_blank">{}</a>',
                obj.match_id,
                str(obj.match_id)[:8] + "..."
            )
        return '-'
    match_link.short_description = 'Match'
    
    def stats_summary(self, obj):
        return format_html(
            '<strong>{}%</strong> ({}/{}) | Streak: {} (Best: {})',
            obj.hit_percentage,
            obj.total_hits,
            obj.total_shots,
            obj.current_streak,
            obj.best_streak
        )
    stats_summary.short_description = 'Stats'
    
    def hit_rate_display(self, obj):
        return f"{obj.hit_percentage}% ({obj.total_hits}/{obj.total_shots})"
    hit_rate_display.short_description = 'Hit Rate'
    
    def duration(self, obj):
        if obj.ended_at:
            duration = obj.ended_at - obj.started_at
            total_seconds = int(duration.total_seconds())
            hours, remainder = divmod(total_seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            
            if hours > 0:
                return f"{hours}h {minutes}m"
            elif minutes > 0:
                return f"{minutes}m {seconds}s"
            else:
                return f"{seconds}s"
        return "Active"
    duration.short_description = 'Duration'


@admin.register(ShotEvent)
class ShotEventAdmin(admin.ModelAdmin):
    list_display = ['id', 'session_link', 'idx', 'hit_miss', 'timestamp']
    list_filter = ['is_hit', 'timestamp']
    search_fields = ['session__user__username']
    readonly_fields = ['session', 'idx', 'timestamp']
    ordering = ['-timestamp']
    
    def session_link(self, obj):
        url = reverse('admin:shooting_shotsession_change', args=[obj.session.id])
        return format_html('<a href="{}">{}</a>', url, str(obj.session.id)[:8] + "...")
    session_link.short_description = 'Session'
    
    def hit_miss(self, obj):
        if obj.is_hit:
            return format_html('<span style="color: green; font-weight: bold;">HIT</span>')
        else:
            return format_html('<span style="color: red; font-weight: bold;">MISS</span>')
    hit_miss.short_description = 'Result'
    
    def has_add_permission(self, request):
        return False  # Prevent manual event creation


@admin.register(EarnedAchievement)
class EarnedAchievementAdmin(admin.ModelAdmin):
    list_display = ['user', 'achievement', 'session_link', 'earned_at']
    list_filter = ['achievement', 'earned_at']
    search_fields = ['user__username', 'achievement__name']
    readonly_fields = ['user', 'session', 'achievement', 'earned_at']
    ordering = ['-earned_at']
    
    def session_link(self, obj):
        url = reverse('admin:shooting_shotsession_change', args=[obj.session.id])
        return format_html('<a href="{}">{}</a>', url, str(obj.session.id)[:8] + "...")
    session_link.short_description = 'Session'
    
    def has_add_permission(self, request):
        return False  # Prevent manual creation


# Custom admin actions
@admin.action(description='End selected active sessions')
def end_sessions(modeladmin, request, queryset):
    active_sessions = queryset.filter(is_active=True)
    count = active_sessions.count()
    
    for session in active_sessions:
        session.end_session()
    
    modeladmin.message_user(request, f'Successfully ended {count} sessions.')

ShotSessionAdmin.actions = [end_sessions]
