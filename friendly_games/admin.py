from django.contrib import admin
from .models import PlayerCodename, FriendlyGame, FriendlyGamePlayer, FriendlyGameStatistics, FriendlyGameResult


@admin.register(PlayerCodename)
class PlayerCodenameAdmin(admin.ModelAdmin):
    list_display = ['player', 'codename', 'created_at', 'updated_at']
    list_filter = ['created_at', 'updated_at']
    search_fields = ['player__name', 'codename']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['player__name']


@admin.register(FriendlyGame)
class FriendlyGameAdmin(admin.ModelAdmin):
    list_display = ['name', 'match_number', 'status', 'validation_status', 'created_at', 'completed_at']
    list_filter = ['status', 'validation_status', 'created_at']
    search_fields = ['name', 'match_number', 'game_pin']
    readonly_fields = ['created_at', 'started_at', 'completed_at']
    ordering = ['-created_at']


@admin.register(FriendlyGamePlayer)
class FriendlyGamePlayerAdmin(admin.ModelAdmin):
    list_display = ['player', 'game', 'team', 'position', 'codename_verified', 'provided_codename']
    list_filter = ['team', 'position', 'codename_verified', 'created_at']
    search_fields = ['player__name', 'game__name', 'provided_codename']
    readonly_fields = ['created_at']
    ordering = ['-created_at']


@admin.register(FriendlyGameStatistics)
class FriendlyGameStatisticsAdmin(admin.ModelAdmin):
    list_display = ['player', 'total_games', 'total_wins', 'total_losses', 'win_rate', 'last_updated']
    list_filter = ['last_updated']
    search_fields = ['player__name']
    readonly_fields = ['last_updated']
    ordering = ['-total_games']



@admin.register(FriendlyGameResult)
class FriendlyGameResultAdmin(admin.ModelAdmin):
    list_display = ['game', 'submitted_by_team', 'validated_by_team', 'validation_action', 'submitter_verified', 'validator_verified', 'submitted_at', 'validated_at']
    list_filter = ['submitted_by_team', 'validated_by_team', 'validation_action', 'submitter_verified', 'validator_verified', 'submitted_at']
    search_fields = ['game__name', 'game__match_number', 'submitter_codename', 'validator_codename']
    readonly_fields = ['submitted_at', 'validated_at']
    ordering = ['-submitted_at']
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('game')

