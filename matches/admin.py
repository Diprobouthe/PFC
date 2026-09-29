from django.contrib import admin, messages
from django.urls import reverse
from django.utils.html import format_html

from pfc_core.admin_filters import ActiveTeamMixin, ActiveTournamentMixin

from .lifecycle import (
    LIVE_COURT_STATUSES,
    MatchLifecycleError,
    activate_verified_match,
    cancel_stale_match,
    process_round_transition,
    process_tournament_transition,
    release_court_and_requeue_match,
)
from .models import Match, MatchActivation, MatchLifecycleTransition, MatchResult, NextOpponentRequest


class MatchActivationInline(admin.TabularInline):
    model = MatchActivation
    extra = 0
    can_delete = False
    readonly_fields = ["team", "pin_used", "is_initiator", "activated_at"]

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class MatchResultInline(admin.TabularInline):
    model = MatchResult
    extra = 0
    can_delete = False
    readonly_fields = ["submitted_by", "validated_by", "photo_evidence", "notes", "submitted_at", "validated_at"]

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Match)
class MatchAdmin(ActiveTeamMixin, ActiveTournamentMixin, admin.ModelAdmin):
    """Operational Match administration without raw lifecycle writes.

    Every state-changing action delegates to ``matches.lifecycle``. The legacy
    GET-only quick links are intentionally absent: they did not carry the
    required Match-side proof or lifecycle data and routed to obsolete paths.
    """

    list_display = (
        "id",
        "tournament",
        "team1",
        "team2",
        "status_badge",
        "score_display",
        "court_display",
        "timer_status",
        "timing_display",
    )
    list_filter = ("status", "tournament", "round", "start_time")
    search_fields = ("team1__name", "team2__name", "tournament__name")
    date_hierarchy = "start_time"
    inlines = [MatchActivationInline, MatchResultInline]
    readonly_fields = (
        "status",
        "court",
        "proposed_court",
        "waiting_for_court",
        "team1_score",
        "team2_score",
        "start_time",
        "end_time",
        "duration",
    )
    fieldsets = (
        (None, {"fields": ("tournament", "round", "bracket")}),
        ("Teams", {"fields": ("team1", "team2")}),
        ("Status", {"fields": ("status",)}),
        ("Court Assignment", {"fields": ("court", "proposed_court", "waiting_for_court")}),
        ("Scores", {"fields": ("team1_score", "team2_score")}),
        (
            "Timer Configuration",
            {
                "fields": ("time_limit_minutes",),
                "description": "Set time limit in minutes (optional). Timer starts when both teams activate the match.",
            },
        ),
        ("Timing", {"fields": ("start_time", "end_time", "duration", "timer_expired", "timer_expired_at")} ),
    )
    actions = (
        "activate_or_assign_court",
        "release_court_and_requeue",
        "cancel_match_and_release_court",
        "retry_lifecycle_transition",
    )

    def has_add_permission(self, request):
        # Tournament Match creation belongs to tournament generators only.
        return False

    def has_delete_permission(self, request, obj=None):
        # Deletion can strand a Court occupancy flag and erase lifecycle history.
        return False

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj and obj.status != "pending":
            fields.extend(
                field.name
                for field in obj._meta.concrete_fields
                if field.name not in {"id", "created_at", "updated_at"}
            )
        return tuple(dict.fromkeys(fields))

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {
            "pending": ("#FFC107", "#000", "Pending"),
            "pending_verification": ("#FF9800", "#000", "Partially Activated"),
            "active": ("#28A745", "#fff", "Active"),
            "waiting_validation": ("#17A2B8", "#fff", "Waiting Validation"),
            "completed": ("#007BFF", "#fff", "Completed"),
            "cancelled": ("#6C757D", "#fff", "Cancelled"),
        }
        background, color, label = colors.get(obj.status, ("#6C757D", "#fff", obj.status))
        return format_html(
            '<span style="background-color: {}; padding: 3px 8px; border-radius: 10px; color: {};">{}</span>',
            background,
            color,
            label,
        )

    @admin.display(description="Score")
    def score_display(self, obj):
        if obj.team1_score is not None and obj.team2_score is not None:
            return format_html("<strong>{}</strong> - <strong>{}</strong>", obj.team1_score, obj.team2_score)
        return "No score"

    @admin.display(description="Court")
    def court_display(self, obj):
        if obj.court_id:
            return format_html(
                '<a href="{}">{}</a>',
                reverse("admin:courts_court_change", args=[obj.court_id]),
                obj.court.number,
            )
        return "Not assigned"

    @admin.display(description="Timer")
    def timer_status(self, obj):
        if not obj.time_limit_minutes:
            return "No timer"
        if obj.status not in ["active", "waiting_validation"]:
            return format_html('<span style="color: #6c757d;">⏱️ {} min</span>', obj.time_limit_minutes)
        if obj.is_time_expired:
            return format_html('<span style="color: #dc3545; font-weight: bold;">⏰ EXPIRED</span>')
        return format_html('<span style="color: #28a745; font-weight: bold;">⏱️ {}</span>', obj.time_remaining_display)

    @admin.display(description="Duration")
    def timing_display(self, obj):
        if obj.start_time and obj.end_time:
            return format_html("{}m", obj.duration or "N/A")
        if obj.start_time:
            return "In progress"
        return "Not started"

    @admin.action(description="Activate / assign an eligible Court")
    def activate_or_assign_court(self, request, queryset):
        for match in queryset.order_by("pk"):
            if match.status != "pending_verification":
                self.message_user(
                    request,
                    f"Match {match.id}: activation is valid only after both sides have verified.",
                    messages.WARNING,
                )
                continue
            try:
                outcome = activate_verified_match(match.id)
            except MatchLifecycleError as exc:
                self.message_user(request, f"Match {match.id}: {exc}", messages.ERROR)
                continue
            if outcome.activated:
                self.message_user(request, f"Match {match.id}: activated on Court {outcome.court_id}.", messages.SUCCESS)
            else:
                self.message_user(request, f"Match {match.id}: queued until a compatible Court is free.", messages.INFO)

    @admin.action(description="Release Court and requeue active Match")
    def release_court_and_requeue(self, request, queryset):
        for match in queryset.order_by("pk"):
            try:
                outcome = release_court_and_requeue_match(match.id)
            except MatchLifecycleError as exc:
                self.message_user(request, f"Match {match.id}: {exc}", messages.ERROR)
                continue
            self.message_user(
                request,
                f"Match {outcome.match_id}: released Court {outcome.court_id} and returned to the verified Court queue.",
                messages.SUCCESS,
            )

    @admin.action(description="Cancel pending, verified, or live Match safely")
    def cancel_match_and_release_court(self, request, queryset):
        for match in queryset.order_by("pk"):
            try:
                outcome = cancel_stale_match(match.id)
            except MatchLifecycleError as exc:
                self.message_user(request, f"Match {match.id}: {exc}", messages.ERROR)
                continue
            if outcome.state == "cancelled":
                self.message_user(
                    request,
                    f"Match {match.id}: cancelled safely; any owned Court was released or handed off.",
                    messages.SUCCESS,
                )
            else:
                self.message_user(
                    request,
                    f"Match {match.id}: only pending, verified, or live Matches can be cancelled.",
                    messages.WARNING,
                )

    @admin.action(description="Retry failed Match / Round lifecycle transition")
    def retry_lifecycle_transition(self, request, queryset):
        for match in queryset.order_by("pk"):
            retried = False
            transition = MatchLifecycleTransition.objects.filter(match_id=match.id).first()
            if transition and transition.status in {
                MatchLifecycleTransition.PENDING,
                MatchLifecycleTransition.FAILED,
            }:
                retried = process_tournament_transition(match.id)
            if match.round_id:
                from tournaments.models import RoundLifecycleTransition

                round_transition = RoundLifecycleTransition.objects.filter(round_id=match.round_id).first()
                if round_transition and round_transition.status in {
                    RoundLifecycleTransition.PENDING,
                    RoundLifecycleTransition.FAILED,
                }:
                    retried = process_round_transition(match.round_id) or retried
            if retried:
                self.message_user(request, f"Match {match.id}: lifecycle retry completed.", messages.SUCCESS)
            else:
                self.message_user(request, f"Match {match.id}: no failed or pending lifecycle transition is available to retry.", messages.WARNING)


@admin.register(MatchActivation)
class MatchActivationAdmin(ActiveTeamMixin, ActiveTournamentMixin, admin.ModelAdmin):
    list_display = ("match", "team", "activated_at")
    list_filter = ("activated_at", "team")
    search_fields = ("match__team1__name", "match__team2__name", "team__name")
    readonly_fields = [field.name for field in MatchActivation._meta.concrete_fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MatchResult)
class MatchResultAdmin(ActiveTeamMixin, ActiveTournamentMixin, admin.ModelAdmin):
    list_display = ("match", "submitted_by", "validated_by", "submitted_at", "validated_at")
    list_filter = ("submitted_at", "validated_at")
    search_fields = ("match__team1__name", "match__team2__name", "submitted_by__name", "validated_by__name")
    readonly_fields = [field.name for field in MatchResult._meta.concrete_fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(NextOpponentRequest)
class NextOpponentRequestAdmin(ActiveTeamMixin, ActiveTournamentMixin, admin.ModelAdmin):
    """Historical request records only until a guarded request service exists."""

    list_display = ("tournament", "requesting_team", "target_team", "status_badge", "created_at")
    list_filter = ("status", "tournament", "created_at")
    search_fields = ("requesting_team__name", "target_team__name", "tournament__name")
    readonly_fields = [field.name for field in NextOpponentRequest._meta.concrete_fields]
    actions = []

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Status")
    def status_badge(self, obj):
        colors = {
            "pending": ("#FFC107", "#000"),
            "accepted": ("#28A745", "#fff"),
            "rejected": ("#DC3545", "#fff"),
            "expired": ("#6C757D", "#fff"),
        }
        background, color = colors.get(obj.status, ("#6C757D", "#fff"))
        return format_html(
            '<span style="background-color: {}; padding: 3px 8px; border-radius: 10px; color: {};">{}</span>',
            background,
            color,
            obj.get_status_display(),
        )
