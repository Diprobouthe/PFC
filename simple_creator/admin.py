from django.contrib import admin
from django.utils.html import format_html
from .models import TournamentScenario, VoucherCode, SimpleTournament, ScenarioStage


class ScenarioStageInline(admin.TabularInline):
    model = ScenarioStage
    extra = 1
    fields = ['stage_number', 'name', 'format', 'num_rounds_in_stage', 'num_qualifiers', 'num_matches_per_team']
    ordering = ['stage_number']


@admin.register(TournamentScenario)
class TournamentScenarioAdmin(admin.ModelAdmin):
    list_display = ['display_name', 'name', 'scenario_mode', 'is_free', 'tournament_type', 'draft_type', 'max_singles_players', 'max_doubles_players', 'max_triples_players']
    list_filter = ['is_free', 'scenario_mode', 'tournament_type', 'draft_type']
    search_fields = ['name', 'display_name']
    readonly_fields = ['created_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'display_name', 'description')
        }),
        ('Access Control', {
            'fields': ('is_free', 'requires_voucher')
        }),
        ('Supported Formats', {
            'fields': ('supports_singles', 'supports_doubles', 'supports_triples'),
            'description': (
                'Controls which format cards appear in the user-facing Easy Tournament creator. '
                'Singles / Tête-à-tête uses individual registration with temporary one-player teams — '
                'NOT normal permanent one-player teams. Doubles and Triples use Mêlée-style team shuffling.'
            )
        }),
        ('Player Limits', {
            'fields': ('max_singles_players', 'max_doubles_players', 'max_triples_players'),
            'description': 'Maximum number of individual players allowed per format.'
        }),
        ('Court Configuration', {
            'fields': ('default_court_complex', 'max_courts', 'recommended_courts'),
            'description': 'Court complex is REQUIRED for all tournaments using this scenario.'
        }),
        ('Scenario Mode', {
            'fields': ('scenario_mode', 'vs_config'),
            'description': (
                'Determines what type of tournament is created. '
                'For VS Mode, set scenario_mode to “vs_mode” and optionally configure vs_config. '
                'Leave vs_config blank to use the standard preset: '
                '6 Tête-à-tête (2 pts), 3 Doubles (3 pts), 2 Triples (5 pts). '
                'Example vs_config: {"games": [{"format": "tete_a_tete", "count": 6, "points_per_win": 2}, '
                '{"format": "doublets", "count": 3, "points_per_win": 3}, '
                '{"format": "triplets", "count": 2, "points_per_win": 5}]}'
            )
        }),
        ('Tournament Configuration', {
            'fields': ('tournament_type', 'num_rounds', 'matches_per_team', 'draft_type')
        }),
        ('Timing Configuration', {
            'fields': ('default_time_limit_minutes', 'pregame_countdown_minutes'),
            'description': 'Match time limit and pre-game court countdown. Leave pregame blank to use the system default (3 minutes).'
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        })
    )
    
    inlines = [ScenarioStageInline]


@admin.register(VoucherCode)
class VoucherCodeAdmin(admin.ModelAdmin):
    list_display = ['code', 'scenario', 'is_used', 'used_at', 'used_for_tournament_link']
    list_filter = ['is_used', 'scenario', 'used_at']
    search_fields = ['code']
    readonly_fields = ['used_at', 'used_for_tournament', 'created_at']
    
    def used_for_tournament_link(self, obj):
        if obj.used_for_tournament:
            return format_html(
                '<a href="/admin/tournaments/tournament/{}/change/">{}</a>',
                obj.used_for_tournament.id,
                obj.used_for_tournament.name
            )
        return '-'
    used_for_tournament_link.short_description = 'Tournament'
    
    fieldsets = (
        ('Voucher Information', {
            'fields': ('code', 'scenario')
        }),
        ('Usage Information', {
            'fields': ('is_used', 'used_at', 'used_for_tournament')
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        })
    )
    
    actions = ['generate_vouchers']
    
    def generate_vouchers(self, request, queryset):
        """Admin action to generate multiple vouchers"""
        # This could be enhanced to bulk generate vouchers
        pass
    generate_vouchers.short_description = "Generate vouchers for selected scenarios"


@admin.register(SimpleTournament)
class SimpleTournamentAdmin(admin.ModelAdmin):
    list_display = ['tournament_link', 'scenario', 'format_type', 'court_complex', 'is_completed', 'created_at']
    list_filter = ['scenario', 'format_type', 'is_completed', 'created_at']
    search_fields = ['tournament__name']
    readonly_fields = ['tournament', 'auto_start_date', 'auto_end_date', 'created_at']
    
    def tournament_link(self, obj):
        return format_html(
            '<a href="/admin/tournaments/tournament/{}/change/">{}</a>',
            obj.tournament.id,
            obj.tournament.name
        )
    tournament_link.short_description = 'Tournament'
    
    fieldsets = (
        ('Tournament Information', {
            'fields': ('tournament', 'scenario', 'format_type', 'court_complex')
        }),
        ('Voucher Information', {
            'fields': ('voucher_used',)
        }),
        ('Auto-Generated Settings', {
            'fields': ('auto_start_date', 'auto_end_date', 'team_pins_generated')
        }),
        ('Completion Status', {
            'fields': ('is_completed', 'badges_assigned', 'players_restored', 'mele_teams_deleted')
        }),
        ('Metadata', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        })
    )
    
    actions = ['trigger_cleanup']
    
    def trigger_cleanup(self, request, queryset):
        """Admin action to manually trigger cleanup for completed tournaments"""
        for simple_tournament in queryset:
            if simple_tournament.is_completed:
                simple_tournament.auto_cleanup()
        self.message_user(request, f"Cleanup triggered for {queryset.count()} tournaments.")
    trigger_cleanup.short_description = "Trigger cleanup for selected tournaments"
