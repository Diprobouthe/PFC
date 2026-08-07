from django.contrib import admin
from .models import CertifyingEntity, PlayerCertRating, CertRatingHistory


@admin.register(CertifyingEntity)
class CertifyingEntityAdmin(admin.ModelAdmin):
    list_display = ("name", "rating_system", "is_active", "elo_starting_rating", "elo_k_factor", "elo_scale", "created_at")
    list_filter = ("is_active", "rating_system")
    search_fields = ("name",)
    fieldsets = (
        (None, {
            "fields": ("name", "is_active", "rating_system"),
        }),
        ("Classic Elo Parameters", {
            "fields": ("elo_starting_rating", "elo_k_factor", "elo_scale"),
            "description": (
                "These parameters apply when rating_system = classic_elo. "
                "Changing them after ratings have been calculated will not recalculate historical entries."
            ),
        }),
    )


@admin.register(PlayerCertRating)
class PlayerCertRatingAdmin(admin.ModelAdmin):
    list_display = ("player", "entity", "current_rating", "matches_played", "updated_at")
    list_filter = ("entity",)
    search_fields = ("player__name", "entity__name")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("entity", "-current_rating")


@admin.register(CertRatingHistory)
class CertRatingHistoryAdmin(admin.ModelAdmin):
    list_display = ("player", "entity", "match", "rating_before", "rating_after", "rating_change", "timestamp")
    list_filter = ("entity",)
    search_fields = ("player__name", "entity__name")
    readonly_fields = ("player", "entity", "match", "rating_before", "rating_after", "rating_change", "timestamp")
    ordering = ("-timestamp",)

    def has_add_permission(self, request):
        return False  # history is created only by the processor

    def has_change_permission(self, request, obj=None):
        return False  # history is immutable
