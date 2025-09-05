from django.contrib import admin
from .models import Leaderboard, LeaderboardEntry, TeamStatistics, MatchStatistics

class LeaderboardEntryInline(admin.TabularInline):
    model = LeaderboardEntry
    extra = 0
    readonly_fields = ['position']

@admin.register(Leaderboard)
class LeaderboardAdmin(admin.ModelAdmin):
    list_display = ('tournament', 'last_updated')
    search_fields = ('tournament__name',)
    inlines = [LeaderboardEntryInline]
    readonly_fields = ['last_updated']
    actions = ['update_leaderboard']
    
    def update_leaderboard(self, request, queryset):
        from .views import update_tournament_leaderboard
        for leaderboard in queryset:
            update_tournament_leaderboard(leaderboard.tournament)
    update_leaderboard.short_description = "Update selected leaderboards"

@admin.register(LeaderboardEntry)
class LeaderboardEntryAdmin(admin.ModelAdmin):
    list_display = ('leaderboard', 'team', 'position', 'matches_played', 'matches_won', 'matches_lost', 'points_scored', 'points_conceded')
    list_filter = ('leaderboard__tournament',)
    search_fields = ('team__name', 'leaderboard__tournament__name')
    readonly_fields = ['position']

@admin.register(TeamStatistics)
class TeamStatisticsAdmin(admin.ModelAdmin):
    list_display = ('team', 'total_matches_played', 'total_matches_won', 'total_matches_lost', 'tournaments_participated', 'tournaments_won')
    list_filter = ('tournaments_participated', 'tournaments_won')
    search_fields = ('team__name',)
    readonly_fields = ['last_updated']

@admin.register(MatchStatistics)
class MatchStatisticsAdmin(admin.ModelAdmin):
    list_display = ('match', 'match_duration_minutes')
    search_fields = ('match__team1__name', 'match__team2__name')
    readonly_fields = []
