from django.contrib import admin
from .models import Invitation, TeamBuildSession


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display  = ("id", "invite_type", "sender", "recipient", "status", "created_at")
    list_filter   = ("invite_type", "status")
    search_fields = ("sender__name", "recipient__name", "message")
    readonly_fields = ("token", "created_at", "responded_at")


@admin.register(TeamBuildSession)
class TeamBuildSessionAdmin(admin.ModelAdmin):
    list_display  = ("id", "creator", "build_type", "status", "accepted_count", "target_size", "created_at")
    list_filter   = ("build_type", "status")
    search_fields = ("creator__name", "proposed_team_name")
    readonly_fields = ("token", "created_at", "completed_at")
    filter_horizontal = ("accepted_players",)

    def accepted_count(self, obj):
        return obj.accepted_count
    accepted_count.short_description = "Accepted"
