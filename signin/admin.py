from django.contrib import admin
from .models import TeamTournamentSignin

@admin.register(TeamTournamentSignin)
class TeamTournamentSigninAdmin(admin.ModelAdmin):
    list_display = ('team', 'tournament', 'signed_in_at', 'is_active')
    list_filter = ('tournament', 'is_active', 'signed_in_at')
    search_fields = ('team__name', 'tournament__name')
    date_hierarchy = 'signed_in_at'
    readonly_fields = ['signed_in_at']
    autocomplete_fields = ['team', 'tournament']
    actions = ['activate_signins', 'deactivate_signins']
    
    def activate_signins(self, request, queryset):
        queryset.update(is_active=True)
    activate_signins.short_description = "Mark selected sign-ins as active"
    
    def deactivate_signins(self, request, queryset):
        queryset.update(is_active=False)
    deactivate_signins.short_description = "Mark selected sign-ins as inactive"
