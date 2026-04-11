"""
Admin Configuration for Practice App

Provides Django admin interface for managing practice sessions and statistics.
Follows PFC admin patterns and maintains read-only approach for data integrity.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import PracticeSession, Shot, PracticeStatistics


@admin.register(PracticeSession)
class PracticeSessionAdmin(admin.ModelAdmin):
    """Admin interface for Practice Sessions"""
    
    list_display = [
        'player_codename', 
        'practice_type', 
        'started_at', 
        'session_duration',
        'total_shots', 
        'hit_percentage_display',
        'is_active',
        'view_shots_link'
    ]
    
    list_filter = [
        'practice_type',
        'is_active',
        'started_at',
    ]
    
    search_fields = [
        'player_codename',
    ]
    
    readonly_fields = [
        'id',
        'started_at',
        'ended_at',
        'total_shots',
        'hits',
        'carreaux',
        'misses',
        'session_duration',
        'hit_percentage_display',
        'carreau_percentage_display',
    ]
    
    fieldsets = (
        ('Session Info', {
            'fields': ('id', 'player_codename', 'practice_type', 'is_active')
        }),
        ('Timing', {
            'fields': ('started_at', 'ended_at', 'session_duration')
        }),
        ('Statistics', {
            'fields': (
                'total_shots', 
                'hits', 
                'carreaux', 
                'misses',
                'hit_percentage_display',
                'carreau_percentage_display'
            )
        }),
        ('Metadata', {
            'fields': ('distance', 'court', 'terrain', 'notes'),
            'classes': ('collapse',)
        }),
    )
    
    ordering = ['-started_at']
    
    def session_duration(self, obj):
        """Display session duration"""
        return obj.duration
    session_duration.short_description = 'Duration'
    
    def hit_percentage_display(self, obj):
        """Display hit percentage with color coding"""
        percentage = obj.hit_percentage
        if percentage >= 80:
            color = 'green'
        elif percentage >= 60:
            color = 'orange'
        else:
            color = 'red'
        
        return format_html(
            '<span style="color: {}; font-weight: bold;">{:.1f}%</span>',
            color,
            percentage
        )
    hit_percentage_display.short_description = 'Hit %'
    
    def carreau_percentage_display(self, obj):
        """Display carreau percentage"""
        return f"{obj.carreau_percentage:.1f}%"
    carreau_percentage_display.short_description = 'Carreau %'
    
    def view_shots_link(self, obj):
        """Link to view shots for this session"""
        url = reverse('admin:practice_shot_changelist') + f'?session__id__exact={obj.id}'
        return format_html('<a href="{}">View Shots ({})</a>', url, obj.total_shots)
    view_shots_link.short_description = 'Shots'
    
    def has_add_permission(self, request):
        """Prevent manual session creation - sessions are created via API"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Allow deletion for cleanup purposes"""
        return True


@admin.register(Shot)
class ShotAdmin(admin.ModelAdmin):
    """Admin interface for individual shots"""
    
    list_display = [
        'session_player',
        'sequence_number',
        'outcome_display',
        'timestamp',
        'session_link'
    ]
    
    list_filter = [
        'outcome',
        'timestamp',
        'session__practice_type',
    ]
    
    search_fields = [
        'session__player_codename',
    ]
    
    readonly_fields = [
        'id',
        'session',
        'sequence_number',
        'outcome',
        'timestamp',
        'session_info',
    ]
    
    fieldsets = (
        ('Shot Details', {
            'fields': ('id', 'session_info', 'sequence_number', 'outcome', 'timestamp')
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
    )
    
    ordering = ['-timestamp']
    
    def session_player(self, obj):
        """Display session player codename"""
        return obj.session.player_codename
    session_player.short_description = 'Player'
    
    def outcome_display(self, obj):
        """Display outcome with color coding"""
        colors = {
            'hit': 'green',
            'carreau': 'orange',
            'miss': 'red'
        }
        color = colors.get(obj.outcome, 'black')
        
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_outcome_display()
        )
    outcome_display.short_description = 'Outcome'
    
    def session_link(self, obj):
        """Link to parent session"""
        url = reverse('admin:practice_practicesession_change', args=[obj.session.id])
        return format_html('<a href="{}">Session</a>', url)
    session_link.short_description = 'Session'
    
    def session_info(self, obj):
        """Display session information"""
        return f"{obj.session.player_codename} - {obj.session.started_at.strftime('%Y-%m-%d %H:%M')}"
    session_info.short_description = 'Session Info'
    
    def has_add_permission(self, request):
        """Prevent manual shot creation - shots are created via API"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """Prevent shot modification to maintain data integrity"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Allow deletion for cleanup purposes"""
        return True


@admin.register(PracticeStatistics)
class PracticeStatisticsAdmin(admin.ModelAdmin):
    """Admin interface for practice statistics"""
    
    list_display = [
        'player_codename',
        'total_sessions',
        'total_shots',
        'overall_hit_percentage_display',
        'best_hit_streak',
        'last_updated'
    ]
    
    search_fields = [
        'player_codename',
    ]
    
    readonly_fields = [
        'player_codename',
        'total_sessions',
        'total_shots',
        'total_hits',
        'total_carreaux',
        'total_misses',
        'best_hit_streak',
        'overall_hit_percentage_display',
        'overall_carreau_percentage_display',
        'last_updated',
    ]
    
    fieldsets = (
        ('Player Info', {
            'fields': ('player_codename', 'last_updated')
        }),
        ('Session Statistics', {
            'fields': ('total_sessions', 'average_session_length')
        }),
        ('Shot Statistics', {
            'fields': (
                'total_shots',
                'total_hits',
                'total_carreaux', 
                'total_misses',
                'overall_hit_percentage_display',
                'overall_carreau_percentage_display'
            )
        }),
        ('Performance Metrics', {
            'fields': ('best_hit_streak', 'common_miss_position')
        }),
    )
    
    ordering = ['-total_shots']
    
    def overall_hit_percentage_display(self, obj):
        """Display overall hit percentage with color coding"""
        percentage = obj.overall_hit_percentage
        if percentage >= 80:
            color = 'green'
        elif percentage >= 60:
            color = 'orange'
        else:
            color = 'red'
        
        return format_html(
            '<span style="color: {}; font-weight: bold;">{:.1f}%</span>',
            color,
            percentage
        )
    overall_hit_percentage_display.short_description = 'Overall Hit %'
    
    def overall_carreau_percentage_display(self, obj):
        """Display overall carreau percentage"""
        return f"{obj.overall_carreau_percentage:.1f}%"
    overall_carreau_percentage_display.short_description = 'Overall Carreau %'
    
    def has_add_permission(self, request):
        """Prevent manual statistics creation - stats are auto-generated"""
        return False
    
    def has_change_permission(self, request, obj=None):
        """Prevent manual statistics modification"""
        return False
    
    def has_delete_permission(self, request, obj=None):
        """Allow deletion for cleanup purposes"""
        return True


# Customize admin site header
admin.site.site_header = "PFC Practice Administration"
admin.site.site_title = "PFC Practice Admin"
admin.site.index_title = "Practice Module Management"
