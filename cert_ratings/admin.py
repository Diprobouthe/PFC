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


from django import forms
from django.core.exceptions import ValidationError
from .peta_models import PetaSeries, PetaEvent


@admin.register(PetaSeries)
class PetaSeriesAdmin(admin.ModelAdmin):
    list_display = ("name", "entity", "rules_commitment", "created_at")
    search_fields = ("name", "entity__name")


class PetaEventAdminForm(forms.ModelForm):
    class Meta:
        model = PetaEvent
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        series = cleaned.get("series")
        tournament = cleaned.get("tournament")
        ordinal = cleaned.get("ordinal")
        if series and series.entity.rating_system != "peta_algorithm":
            raise ValidationError("PETA Series entity must use the PETA algorithm.")
        if series and tournament and tournament.certifying_entity_id != series.entity_id:
            raise ValidationError(
                "Tournament certification must match the selected PETA Series entity."
            )
        if series and ordinal and not self.instance.pk:
            prior = PetaEvent.objects.filter(series=series, ordinal__lt=ordinal)
            if ordinal > 1 and prior.count() != ordinal - 1:
                raise ValidationError(
                    "Create PETA events in ordinal order, beginning with event 1."
                )
        return cleaned


@admin.register(PetaEvent)
class PetaEventAdmin(admin.ModelAdmin):
    form = PetaEventAdminForm
    list_display = ("tournament", "series", "ordinal", "settled_at")
    list_filter = ("series", "settled_at")
    search_fields = ("tournament__name", "series__name")
    readonly_fields = ("settled_at", "settlement_audit")
