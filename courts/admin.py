from django.contrib import admin, messages
from django.db.models import OuterRef, Subquery
from django.urls import reverse
from django.utils.html import format_html

from .models import Court, CourtComplex, CourtComplexPhoto, CourtComplexRating


@admin.register(Court)
class CourtAdmin(admin.ModelAdmin):
    """Court metadata and read-only lifecycle occupancy operations.

    Court availability is derived from the live Match owner. It remains
    immutable in the generic change form; reconciliation delegates to the
    Match lifecycle service under the Court/Match locks.
    """

    list_display = (
        "number",
        "name",
        "get_complex_name",
        "status_badge",
        "live_match_display",
        "occupancy_health",
    )
    list_filter = ("is_available",)
    search_fields = ("number", "name")
    readonly_fields = ("is_available",)
    fieldsets = (
        (
            None,
            {"fields": ("number", "name", "location_description", "is_available")},
        ),
    )
    actions = ("reconcile_lifecycle_occupancy",)

    def has_delete_permission(self, request, obj=None):
        # Match history references Court rows; deletion is never a recovery tool.
        return False

    def get_queryset(self, request):
        from matches.lifecycle import LIVE_COURT_STATUSES
        from matches.models import Match

        live_matches = Match.objects.filter(
            court_id=OuterRef("pk"),
            status__in=LIVE_COURT_STATUSES,
        ).order_by("pk")
        return super().get_queryset(request).annotate(
            _live_match_id=Subquery(live_matches.values("pk")[:1]),
            _live_match_status=Subquery(live_matches.values("status")[:1]),
        )

    @admin.display(description="Court Complex")
    def get_complex_name(self, obj):
        from .utils import get_court_complex_for_court

        complex_obj = get_court_complex_for_court(obj)
        return complex_obj.name if complex_obj else "Not assigned"

    @admin.display(description="Availability")
    def status_badge(self, obj):
        if obj.is_available:
            return format_html(
                '<span style="background-color: #28A745; padding: 3px 8px; border-radius: 10px; color: #fff;">Available</span>'
            )
        return format_html(
            '<span style="background-color: #DC3545; padding: 3px 8px; border-radius: 10px; color: #fff;">Occupied</span>'
        )

    @admin.display(description="Live Match owner")
    def live_match_display(self, obj):
        if not obj._live_match_id:
            return "None"
        return format_html(
            '<a href="{}">Match {} ({})</a>',
            reverse("admin:matches_match_change", args=[obj._live_match_id]),
            obj._live_match_id,
            obj._live_match_status,
        )

    @admin.display(description="Occupancy health")
    def occupancy_health(self, obj):
        if obj._live_match_id and not obj.is_available:
            return format_html('<span style="color: #198754;">Consistent</span>')
        if obj._live_match_id and obj.is_available:
            return format_html('<strong style="color: #dc3545;">Inconsistent: live Match is not reserved</strong>')
        if not obj._live_match_id and not obj.is_available:
            return format_html('<strong style="color: #dc3545;">Orphaned occupied state</strong>')
        return format_html('<span style="color: #198754;">Consistent</span>')

    @admin.action(description="Reconcile Court occupancy through Match lifecycle")
    def reconcile_lifecycle_occupancy(self, request, queryset):
        from matches.lifecycle import MatchLifecycleError, reconcile_court_occupancy

        for court in queryset.order_by("pk"):
            try:
                outcome = reconcile_court_occupancy(court.id)
            except MatchLifecycleError as exc:
                self.message_user(request, f"Court {court.number}: {exc}", messages.ERROR)
                continue

            if outcome.state == "reconciled_available":
                self.message_user(
                    request,
                    f"Court {court.number}: orphaned occupied state reconciled; a compatible waiting Match may now be promoted.",
                    messages.SUCCESS,
                )
            elif outcome.state == "owned_by_live_match":
                self.message_user(
                    request,
                    f"Court {court.number}: preserved as occupied by Match {outcome.match_id}.",
                    messages.INFO,
                )
            else:
                self.message_user(request, f"Court {court.number}: already available.", messages.INFO)


@admin.register(CourtComplex)
class CourtComplexAdmin(admin.ModelAdmin):
    list_display = ("name", "timezone_name", "get_court_count", "get_court_numbers", "public_accessibility", "average_rating")
    list_filter = ("public_accessibility", "has_shadow_daytime", "has_night_lighting", "timezone_name")
    search_fields = ("name", "description")
    filter_horizontal = ("courts",)

    fieldsets = (
        ("Basic Information", {"fields": ("name", "description", "courts")}),
        (
            "Timezone",
            {
                "fields": ("timezone_name",),
                "description": (
                    'IANA timezone name for this court complex (e.g. "Europe/Athens", "America/New_York"). '
                    "Used to compute court-local date/time for presence and analytics."
                ),
            },
        ),
        (
            "Facility Information",
            {
                "fields": (
                    "distance_to_toilet",
                    "distance_to_water_hose",
                    "has_shadow_daytime",
                    "has_night_lighting",
                    "public_accessibility",
                )
            },
        ),
        (
            "Location & Contact",
            {
                "fields": ("google_maps_url", "latitude", "longitude", "public_hours"),
                "description": "Set latitude and longitude for the optional Friendly nearby-player proximity check. Google Maps links remain unchanged.",
            },
        ),
    )

    @admin.display(description="Courts Count")
    def get_court_count(self, obj):
        return obj.get_court_count()

    @admin.display(description="Court Numbers")
    def get_court_numbers(self, obj):
        numbers = obj.get_court_numbers()
        return ", ".join(map(str, numbers)) if numbers else "No courts assigned"


@admin.register(CourtComplexRating)
class CourtComplexRatingAdmin(admin.ModelAdmin):
    list_display = ("court_complex", "codename", "stars", "created_at")
    list_filter = ("stars", "created_at")
    search_fields = ("court_complex__name", "codename")


@admin.register(CourtComplexPhoto)
class CourtComplexPhotoAdmin(admin.ModelAdmin):
    list_display = ("court_complex", "caption", "uploaded_at")
    list_filter = ("uploaded_at",)
    search_fields = ("court_complex__name", "caption")
