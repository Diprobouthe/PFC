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
    list_display = ['display_name', 'name', 'is_free', 'tournament_type', 'draft_type', 'max_doubles_players', 'max_triples_players']
    list_filter = ['is_free', 'tournament_type', 'draft_type']
    search_fields = ['name', 'display_name']
    readonly_fields = ['created_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'display_name', 'description')
        }),
        ('Access Control', {
            'fields': ('is_free', 'requires_voucher')
        }),
        ('Player Limits', {
            'fields': ('max_doubles_players', 'max_triples_players')
        }),
        ('Court Configuration', {
            'fields': ('default_court_complex', 'max_courts', 'recommended_courts'),
            'description': 'Court complex is REQUIRED for all tournaments using this scenario.'
        }),
        ('Tournament Configuration', {
            'fields': ('tournament_type', 'num_rounds', 'matches_per_team', 'draft_type')
        }),
        ('Match Timer Configuration', {
            'fields': ('default_time_limit_minutes',),
            'description': 'Set default time limit for all matches in tournaments using this scenario.'
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
