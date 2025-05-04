from django.contrib import admin
from .models import Team, Player, TeamAvailability

class PlayerInline(admin.TabularInline):
    model = Player
    extra = 1

class TeamAvailabilityInline(admin.TabularInline):
    model = TeamAvailability
    extra = 0

@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ('name', 'pin', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('name', 'pin')
    date_hierarchy = 'created_at'
    inlines = [PlayerInline, TeamAvailabilityInline]
    fieldsets = (
        (None, {
            'fields': ('name', 'pin')
        }),
    )
    readonly_fields = ['created_at']

@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ('name', 'team', 'is_captain')
    list_filter = ('team', 'is_captain')
    search_fields = ('name', 'team__name')
    autocomplete_fields = ['team']

@admin.register(TeamAvailability)
class TeamAvailabilityAdmin(admin.ModelAdmin):
    list_display = ('team', 'available_from', 'available_to')
    list_filter = ('available_from', 'available_to')
    search_fields = ('team__name', 'notes')
    autocomplete_fields = ['team']
    date_hierarchy = 'available_from'
