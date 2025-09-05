from django.contrib import admin
from django.utils.html import format_html
from .models import TournamentScenario, VoucherCode, SimpleTournament


@admin.register(TournamentScenario)
class TournamentScenarioAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_free', 'format_type', 'num_rounds', 'team_building_method', 'is_active']
    list_filter = ['is_free', 'format_type', 'team_building_method', 'is_active']
    search_fields = ['name', 'description']
    ordering = ['name']


@admin.register(VoucherCode)
class VoucherCodeAdmin(admin.ModelAdmin):
    list_display = ['code', 'scenario', 'is_used', 'used_by', 'created_at', 'expires_at']
    list_filter = ['is_used', 'scenario', 'created_at']
    search_fields = ['code', 'used_by']
    readonly_fields = ['used_at', 'used_for_tournament']
    ordering = ['-created_at']
    
    actions = ['generate_vouchers']
    
    def generate_vouchers(self, request, queryset):
        """Admin action to generate multiple vouchers."""
        # This would be implemented to bulk generate vouchers
        pass
    generate_vouchers.short_description = "Generate vouchers for selected scenarios"


@admin.register(SimpleTournament)
class SimpleTournamentAdmin(admin.ModelAdmin):
    list_display = ['name', 'scenario', 'format', 'status', 'created_by', 'created_at', 'tournament_link']
    list_filter = ['status', 'scenario', 'format', 'created_at']
    search_fields = ['name', 'created_by']
    readonly_fields = ['tournament', 'created_at', 'completed_at']
    ordering = ['-created_at']
    
    def tournament_link(self, obj):
        if obj.tournament:
            url = f"/admin/tournaments/tournament/{obj.tournament.id}/change/"
            return format_html('<a href="{}">View Tournament</a>', url)
        return "-"
    tournament_link.short_description = "Tournament"
    
    actions = ['auto_complete_tournaments']
    
    def auto_complete_tournaments(self, request, queryset):
        """Admin action to auto-complete tournaments."""
        completed_count = 0
        for tournament in queryset:
            if tournament.auto_complete():
                completed_count += 1
        
        self.message_user(request, f"Auto-completed {completed_count} tournaments.")
    auto_complete_tournaments.short_description = "Auto-complete selected tournaments"

