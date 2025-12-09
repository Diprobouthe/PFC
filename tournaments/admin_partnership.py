"""
Admin configuration for partnership tracking models
"""

from django.contrib import admin
from tournaments.partnership_models import MeleePartnership, MeleeShuffleHistory


@admin.register(MeleePartnership)
class MeleePartnershipAdmin(admin.ModelAdmin):
    list_display = (
        'tournament',
        'round_number',
        'player1',
        'player2',
        'team_name',
        'created_at'
    )
    list_filter = (
        'tournament',
        'round_number',
        'created_at'
    )
    search_fields = (
        'player1__name',
        'player2__name',
        'team_name',
        'tournament__name'
    )
    readonly_fields = ('created_at',)
    ordering = ('-created_at',)
    
    def has_add_permission(self, request):
        # Partnerships are created automatically, not manually
        return False


@admin.register(MeleeShuffleHistory)
class MeleeShuffleHistoryAdmin(admin.ModelAdmin):
    list_display = (
        'tournament',
        'round_number',
        'shuffle_type',
        'players_shuffled',
        'shuffled_by',
        'shuffled_at'
    )
    list_filter = (
        'shuffle_type',
        'tournament',
        'shuffled_at'
    )
    search_fields = (
        'tournament__name',
        'notes'
    )
    readonly_fields = ('shuffled_at',)
    ordering = ('-shuffled_at',)
    
    fieldsets = (
        ('Tournament Info', {
            'fields': ('tournament', 'round_number')
        }),
        ('Shuffle Details', {
            'fields': ('shuffle_type', 'players_shuffled', 'shuffled_by', 'shuffled_at')
        }),
        ('Notes', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        # Shuffle history is created automatically, not manually
        return False
