import secrets
from io import BytesIO

from django import forms
from django.contrib import admin
from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from .models import (
    Tournament,
    TournamentTeam,
    Round,
    Bracket,
    TournamentCourt,
    Stage,
    MeleePlayer,
    TournamentRegistrationVoucher,
    TournamentRegistrationVoucherRedemption,
)
from .forms import StageForm
from .poule_models import Poule, PouleTeam
from .admin_shuffle import shuffle_melee_players_action
from .admin_melee_swap import MeleePlayerSwapAdminMixin
from pfc_core.admin_filters import ActiveTeamMixin, ActiveTournamentMixin

# --- Inlines --- 

class StageInline(admin.TabularInline):
    """Inline editor for defining stages within a multi-stage tournament"""
    model = Stage
    form = StageForm
    extra = 0  # Don't auto-create empty stages that break match generation
    fields = ("stage_number", "name", "format", "num_rounds_in_stage", "num_qualifiers", "num_matches_per_team")
    ordering = ["stage_number"]
    verbose_name = "Multi-Stage configuration"
    verbose_name_plural = "Multi-Stage configuration"


class TournamentAdminForm(forms.ModelForm):
    """Expose the existing automatic/manual next-Round product choice."""

    automatic_next_round = forms.BooleanField(
        required=False,
        initial=True,
        label="Automatically generate the next Round",
        help_text=(
            "When selected, completing a Round generates one successor when the "
            "Stage has remaining Rounds. Clear it to use Generate next Round manually."
        ),
    )

    class Meta:
        model = Tournament
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["automatic_next_round"].initial = (
                self.instance.automatic_next_round_enabled()
            )

    def save(self, commit=True):
        tournament = super().save(commit=False)
        tournament.set_automatic_next_round(
            self.cleaned_data.get("automatic_next_round", True)
        )
        if commit:
            tournament.save()
            self.save_m2m()
        return tournament

class TournamentTeamInline(ActiveTeamMixin, admin.TabularInline):
    model = TournamentTeam
    extra = 1
    autocomplete_fields = ["team"]
    fields = ("team", "seeding_position", "is_active", "current_stage_number") 

class TournamentCourtInline(admin.TabularInline):
    model = TournamentCourt
    extra = 1

class RoundInline(admin.TabularInline):
    model = Round
    extra = 0
    fields = ("number", "stage", "number_in_stage", "is_complete")
    readonly_fields = ("number", "stage", "number_in_stage", "is_complete")
    ordering = ["number"]

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

# --- Model Admins --- 

@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
    form = TournamentAdminForm
    list_display = (
        "name", 
        "format", 
        "play_format_display", 
        "start_date", 
        "end_date", 
        "is_active", 
        "is_archived", 
        "team_count", 
        "court_count",
    )
    list_filter = (
        "format", 
        "is_multi_stage",
        "has_triplets", 
        "has_doublets", 
        "has_tete_a_tete", 
        "is_melee",
        "is_active", 
        "is_archived", 
        "start_date"
    )
    search_fields = ("name", "description")
    date_hierarchy = "start_date"
    fieldsets = (
        (None, {
            "fields": ("name", "format"),
            "description": (
                "For Multi-Stage, save this Tournament first. The saved change "
                "form then exposes the Multi-Stage configuration section below."
            ),
        }),
        ("Play Formats", {
            "fields": ("has_triplets", "has_doublets", "has_tete_a_tete")
        }),
        ("Mêlée Mode", {
            "fields": ("is_melee", "melee_format", "melee_teams_generated", "shuffle_players_after_round", "max_participants"),
            "classes": ("collapse",),
            "description": "Enable Mêlée mode for individual player registration with automatic team generation. Enable 'Shuffle players after round' for dynamic team mixing."
        }),
        ("Registration", {
            "fields": ("max_teams", "registration_type"),
            "description": "Maximum Teams is optional. Voucher Required uses tournament-specific registration vouchers; Free preserves normal registration.",
        }),
        ("Dates", {
            "fields": ("start_date", "end_date")
        }),
        ("Status", {
            "fields": ("is_active", "is_archived", "current_round_number")
        }),
        ("Round Progression", {
            "fields": ("automatic_next_round",),
            "description": (
                "Round Robin creates one real playing Round at a time. Courts "
                "control activation capacity only; they never reduce a Round's Match count."
            ),
        }),
        ("Description", {
            "fields": ("description",),
            "classes": ("collapse",)
        }),
        ("Advertisement Banner", {
            "fields": ("banner_enabled", "banner_image", "banner_target_url", "banner_alt_text"),
            "classes": ("collapse",),
            "description": "Configure advertisement banner for tournament overview page"
        }),
        ("Match Timer Configuration", {
            "fields": (
                "default_time_limit_minutes",
                "lineup_selection_seconds",
                "pregame_countdown_minutes",
            ),
            "classes": ("collapse",),
            "description": "Lineup selection is one server-controlled Round window in seconds; zero freezes safe defaults immediately. The pre-game countdown controls the separate Find Your Court window after Court allocation."
        }),
        ("Certification", {
            "fields": ("certifying_entity",),
            "classes": ("collapse",),
            "description": "Optional: select a Certifying Entity to enable independent Elo rating updates for this tournament's matches. Leave blank for a non-certified tournament."
        }),
    )
    actions = [
        "make_active", 
        "archive_tournaments", 
        shuffle_melee_players_action,
        "generate_melee_teams_random",
        "generate_melee_teams_balanced",
        "generate_melee_teams_snake_draft",
        "restore_melee_players_to_original_teams",
        "generate_next_round",
    ]
    
    def get_inlines(self, request, obj=None):
        inlines = [TournamentTeamInline, TournamentCourtInline]
        if obj and obj.is_multi_stage:
            inlines.append(StageInline)
        inlines.append(RoundInline)
        return inlines

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        form.base_fields["format"].help_text = (
            "Choose Multi-Stage and save this Tournament before adding Stages. "
            "Django Admin cannot create parent-dependent Stage inlines until the "
            "Tournament has a database ID."
        )
        return form

    def play_format_display(self, obj):
        formats = []
        if obj.has_triplets:
            formats.append("Triplets")
        if obj.has_doublets:
            formats.append("Doublets")
        if obj.has_tete_a_tete:
            formats.append("Tête-à-tête")
        return ", ".join(formats) if formats else "None"
    play_format_display.short_description = "Play Formats"
    
    def team_count(self, obj):
        count = obj.teams.count()
        return format_html("<a href=\"?tournament__id__exact={}\">{} teams</a>", obj.id, count)
    team_count.short_description = "Teams"
    
    def court_count(self, obj):
        count = obj.courts.count()
        return format_html("<a href=\"?tournament__id__exact={}\">{} courts</a>", obj.id, count)
    court_count.short_description = "Courts"
    
    def make_active(self, request, queryset):
        queryset.update(is_active=True, is_archived=False)
    make_active.short_description = "Mark selected tournaments as active"
    
    def archive_tournaments(self, request, queryset):
        queryset.update(is_active=False, is_archived=True)
    archive_tournaments.short_description = "Archive selected tournaments"
    
    def generate_matches(self, request, queryset):
        generated_count = 0
        total_matches_created = 0
        error_count = 0
        
        for tournament in queryset:
            try:
                matches_created = tournament.generate_matches()
                if matches_created is not None and matches_created > 0:
                    generated_count += 1
                    total_matches_created += matches_created
                    self.message_user(request, f"Created {matches_created} matches for {tournament.name}")
                else:
                    self.message_user(request, f"No matches created for {tournament.name} (insufficient teams or other constraints)", level=messages.WARNING)
            except Exception as e:
                error_count += 1
                self.message_user(request, f"Error generating matches for {tournament.name}: {e}", level=messages.ERROR) 
        
        if generated_count > 0:
            if generated_count == 1:
                self.message_user(request, f"Created {total_matches_created} matches for 1 tournament.")
            else:
                self.message_user(request, f"Created {total_matches_created} matches for {generated_count} tournaments.")
        if error_count > 0:
             self.message_user(request, f"Failed to generate matches for {error_count} tournaments.", level=messages.ERROR)
             
    generate_matches.short_description = "Generate matches for selected tournaments"

    @admin.action(description="Generate next Round manually")
    def generate_next_round(self, request, queryset):
        from .automation_engine import TournamentEngine

        for tournament in queryset.order_by("pk"):
            try:
                generated = TournamentEngine(tournament).generate_next_round()
            except Exception as exc:
                self.message_user(
                    request,
                    f"{tournament.name}: could not generate the next Round: {exc}",
                    messages.ERROR,
                )
                continue
            if generated:
                self.message_user(
                    request,
                    f"{tournament.name}: next Round generation completed.",
                    messages.SUCCESS,
                )
            else:
                self.message_user(
                    request,
                    f"{tournament.name}: no eligible next Round is available.",
                    messages.WARNING,
                )
    
    def advance_knockout_tournaments(self, request, queryset):
        """Manually trigger knockout tournament advancement for selected tournaments."""
        advanced_count = 0
        completed_count = 0
        total_matches_created = 0
        error_count = 0
        
        for tournament in queryset:
            if tournament.format != "knockout":
                self.message_user(request, f"{tournament.name} is not a knockout tournament", level=messages.WARNING)
                continue
                
            try:
                advanced, matches_created, tournament_complete = tournament.check_and_advance_knockout_round()
                
                if tournament_complete:
                    completed_count += 1
                    self.message_user(request, f"🏆 Tournament {tournament.name} has been completed!")
                elif advanced:
                    advanced_count += 1
                    total_matches_created += matches_created
                    self.message_user(request, f"✅ {tournament.name}: Advanced to next round with {matches_created} new matches")
                else:
                    self.message_user(request, f"ℹ️ {tournament.name}: Round not yet complete or no advancement needed", level=messages.INFO)
                    
            except Exception as e:
                error_count += 1
                self.message_user(request, f"Error advancing {tournament.name}: {e}", level=messages.ERROR)
        
        # Summary message
        if advanced_count > 0:
            self.message_user(request, f"Advanced {advanced_count} tournaments with {total_matches_created} total new matches")
        if completed_count > 0:
            self.message_user(request, f"Completed {completed_count} tournaments")
        if error_count > 0:
            self.message_user(request, f"Failed to advance {error_count} tournaments", level=messages.ERROR)
            
    advance_knockout_tournaments.short_description = "Advance knockout tournaments to next round"
    
    # Mêlée Team Generation Actions
    def generate_melee_teams_random(self, request, queryset):
        """Generate Mêlée teams using random assignment algorithm"""
        self._generate_melee_teams_with_algorithm(request, queryset, 'random', 'Random Assignment')
    
    generate_melee_teams_random.short_description = "Generate Mêlée teams (Random)"
    
    def generate_melee_teams_balanced(self, request, queryset):
        """Generate Mêlée teams using balanced assignment algorithm"""
        self._generate_melee_teams_with_algorithm(request, queryset, 'balanced', 'Balanced by Skill')
    
    generate_melee_teams_balanced.short_description = "Generate Mêlée teams (Balanced)"
    
    def generate_melee_teams_snake_draft(self, request, queryset):
        """Generate Mêlée teams using snake draft algorithm"""
        self._generate_melee_teams_with_algorithm(request, queryset, 'snake_draft', 'Snake Draft')
    
    generate_melee_teams_snake_draft.short_description = "Generate Mêlée teams (Snake Draft)"
    
    def _generate_melee_teams_with_algorithm(self, request, queryset, algorithm, algorithm_name):
        """Helper method to generate Mêlée teams with specified algorithm"""
        success_count = 0
        error_count = 0
        total_teams_created = 0
        
        for tournament in queryset:
            try:
                if not tournament.is_melee:
                    self.message_user(
                        request, 
                        f"⚠️ {tournament.name}: Not a Mêlée tournament", 
                        level=messages.WARNING
                    )
                    continue
                
                if tournament.melee_teams_generated:
                    self.message_user(
                        request, 
                        f"ℹ️ {tournament.name}: Teams already generated", 
                        level=messages.INFO
                    )
                    continue
                
                teams_created = tournament.generate_melee_teams(algorithm)
                
                if teams_created > 0:
                    success_count += 1
                    total_teams_created += teams_created
                    self.message_user(
                        request, 
                        f"✅ {tournament.name}: Generated {teams_created} teams using {algorithm_name}"
                    )
                else:
                    self.message_user(
                        request, 
                        f"⚠️ {tournament.name}: No teams generated (insufficient players or other issue)", 
                        level=messages.WARNING
                    )
                    
            except Exception as e:
                error_count += 1
                self.message_user(
                    request, 
                    f"❌ Error generating teams for {tournament.name}: {e}", 
                    level=messages.ERROR
                )
        
        # Summary message
        if success_count > 0:
            self.message_user(
                request, 
                f"🎉 Successfully generated {total_teams_created} teams across {success_count} tournaments using {algorithm_name}"
            )
        if error_count > 0:
            self.message_user(
                request, 
                f"❌ Failed to generate teams for {error_count} tournaments", 
                level=messages.ERROR
            )
    
    # Mêlée Player Restoration Action
    def restore_melee_players_to_original_teams(self, request, queryset):
        """Restore mêlée players to their original teams after tournament completion"""
        success_count = 0
        error_count = 0
        total_players_restored = 0
        
        for tournament in queryset:
            try:
                if not tournament.is_melee:
                    self.message_user(
                        request, 
                        f"⚠️ {tournament.name}: Not a Mêlée tournament", 
                        level=messages.WARNING
                    )
                    continue
                
                players_restored = tournament.restore_melee_players_to_original_teams()
                
                if players_restored > 0:
                    success_count += 1
                    total_players_restored += players_restored
                    self.message_user(
                        request, 
                        f"✅ {tournament.name}: Restored {players_restored} players to original teams"
                    )
                else:
                    self.message_user(
                        request, 
                        f"ℹ️ {tournament.name}: No players to restore (already in original teams)", 
                        level=messages.INFO
                    )
                    
            except Exception as e:
                error_count += 1
                self.message_user(
                    request, 
                    f"❌ Error restoring players for {tournament.name}: {e}", 
                    level=messages.ERROR
                )
        
        # Summary message
        if success_count > 0:
            self.message_user(
                request, 
                f"🎉 Successfully restored {total_players_restored} players across {success_count} tournaments"
            )
        if error_count > 0:
            self.message_user(
                request, 
                f"❌ Failed to restore players for {error_count} tournaments", 
                level=messages.ERROR
            )
    
    restore_melee_players_to_original_teams.short_description = "Restore mêlée players to original teams"
    def get_search_results(self, request, queryset, search_term):
        """
        Called by autocomplete_fields widgets that point at Tournament.
        Exclude archived tournaments from autocomplete results.
        """
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        if request.path.endswith('/autocomplete/'):
            queryset = queryset.filter(is_archived=False)
        return queryset, use_distinct


@admin.register(Stage)
class StageAdmin(admin.ModelAdmin):
    form = StageForm
    list_display = ("tournament", "stage_number", "name", "format", "num_rounds_in_stage", "num_qualifiers", "num_matches_per_team", "is_complete", "progression_message")
    list_filter = ("tournament", "format", "is_complete")
    search_fields = ("tournament__name", "name")
    readonly_fields = ("is_complete", "progression_message")
    ordering = ("tournament", "stage_number")
    
    fieldsets = (
        (None, {
            "fields": ("tournament", "stage_number", "name", "format")
        }),
        ("Configuration", {
            "fields": ("num_rounds_in_stage", "num_qualifiers")
        }),
        ("Round Robin Options", {
            "fields": ("num_matches_per_team",),
            "classes": ("collapse",),
            "description": "For Round Robin stages only: leave blank for a full schedule. Otherwise set each Team's total intended matches. The playing Round count is derived when the schedule starts."
        }),
        ("Status", {
            "fields": ("is_complete", "progression_message")
        }),
    )

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj and Round.objects.filter(stage=obj).exists():
            fields.extend(
                [
                    "tournament",
                    "stage_number",
                    "format",
                    "num_qualifiers",
                    "num_rounds_in_stage",
                    "num_matches_per_team",
                ]
            )
        return tuple(dict.fromkeys(fields))

    def has_delete_permission(self, request, obj=None):
        return not (obj and Round.objects.filter(stage=obj).exists())

    def get_search_results(self, request, queryset, search_term):
        """
        Called by autocomplete_fields widgets that point at Stage.
        - Always exclude stages from archived tournaments.
        - When called from the Poule admin change form, restrict to poule-format stages.
        """
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        if request.path.endswith('/autocomplete/'):
            queryset = queryset.filter(tournament__is_archived=False)
            referer = request.META.get('HTTP_REFERER', '')
            if 'tournaments/poule/' in referer:
                queryset = queryset.filter(format='poule')
        return queryset, use_distinct

@admin.register(Round)
class RoundAdmin(admin.ModelAdmin):
    list_display = ("__str__", "tournament", "stage", "number", "number_in_stage", "match_count", "is_complete")
    list_filter = ("tournament", "stage", "is_complete")
    search_fields = ("tournament__name", "stage__name")
    readonly_fields = (
        "tournament",
        "stage",
        "number",
        "number_in_stage",
        "is_complete",
        "lineup_deadline_at",
        "lineups_frozen_at",
    )
    ordering = ("tournament", "number")
    
    def match_count(self, obj):
        count = obj.matches.count()
        return format_html(
            '<a href="{}?round__id__exact={}">{} matches</a>',
            reverse("admin:matches_match_changelist"),
            obj.id,
            count,
        )
    match_count.short_description = "Matches"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(Bracket)
class BracketAdmin(admin.ModelAdmin):
    list_display = ("__str__", "tournament", "get_stage_display", "round", "position") 
    list_filter = ("tournament", "round__stage", "round")
    search_fields = ("tournament__name", "round__stage__name")
    readonly_fields = ("tournament", "round")
    ordering = ("tournament", "round__number", "position")

    def get_stage_display(self, obj):
        if obj.round and obj.round.stage:
            return f"Stage {obj.round.stage.stage_number}"
        return "N/A"
    get_stage_display.short_description = "Stage"
    get_stage_display.admin_order_field = "round__stage__stage_number"

class TournamentRegistrationVoucherBulkGenerateForm(forms.Form):
    """Admin-only input for a single, tournament-specific voucher batch."""

    tournament = forms.ModelChoiceField(
        queryset=Tournament.objects.order_by("name"),
        label="Tournament",
    )
    quantity = forms.IntegerField(
        min_value=1,
        max_value=1000,
        initial=100,
        label="Number of vouchers to generate",
        help_text="Generate between 1 and 1,000 unique tournament-specific codes.",
    )
    uses_per_voucher = forms.IntegerField(
        min_value=1,
        initial=1,
        label="Uses per voucher",
        help_text="Each generated voucher can authorize this many successful registrations.",
    )


class TournamentRegistrationVoucherRedemptionInline(admin.TabularInline):
    model = TournamentRegistrationVoucherRedemption
    extra = 0
    can_delete = False
    readonly_fields = ("team", "player", "redeemed_at")


@admin.register(TournamentRegistrationVoucher)
class TournamentRegistrationVoucherAdmin(admin.ModelAdmin):
    list_display = ("code", "tournament", "is_active", "expires_at", "usage_limit", "redemption_count")
    list_filter = ("is_active", "tournament")
    search_fields = ("code", "tournament__name")
    readonly_fields = ("created_at",)
    fields = ("tournament", "code", "is_active", "expires_at", "usage_limit", "created_at")
    inlines = [TournamentRegistrationVoucherRedemptionInline]
    change_list_template = "admin/tournaments/tournamentregistrationvoucher/change_list.html"

    @admin.display(description="Successful uses")
    def redemption_count(self, obj):
        return obj.redemptions.count()

    def get_urls(self):
        custom_urls = [
            path(
                "bulk-generate/",
                self.admin_site.admin_view(self.bulk_generate_view),
                name="tournaments_tournamentregistrationvoucher_bulk_generate",
            ),
            path(
                "export-pdf/",
                self.admin_site.admin_view(self.export_pdf_view),
                name="tournaments_tournamentregistrationvoucher_export_pdf",
            ),
        ]
        return custom_urls + super().get_urls()

    @staticmethod
    def _new_batch_code(existing_codes):
        """Return a collision-free printable code for the current tournament batch."""
        while True:
            code = f"PFC-{secrets.token_hex(5).upper()}"
            if code not in existing_codes:
                existing_codes.add(code)
                return code

    def bulk_generate_view(self, request):
        """Generate one administrative batch without changing voucher semantics."""
        generated_vouchers = []
        selected_tournament = None
        if request.method == "POST":
            form = TournamentRegistrationVoucherBulkGenerateForm(request.POST)
            if form.is_valid():
                selected_tournament = form.cleaned_data["tournament"]
                quantity = form.cleaned_data["quantity"]
                uses_per_voucher = form.cleaned_data["uses_per_voucher"]
                existing_codes = set(
                    TournamentRegistrationVoucher.objects.filter(
                        tournament=selected_tournament
                    ).values_list("code", flat=True)
                )
                generated_vouchers = [
                    TournamentRegistrationVoucher(
                        tournament=selected_tournament,
                        code=self._new_batch_code(existing_codes),
                        usage_limit=uses_per_voucher,
                    )
                    for _ in range(quantity)
                ]
                TournamentRegistrationVoucher.objects.bulk_create(generated_vouchers)
                generated_vouchers = list(
                    TournamentRegistrationVoucher.objects.filter(
                        tournament=selected_tournament,
                        code__in=[voucher.code for voucher in generated_vouchers],
                    ).order_by("code")
                )
                self.message_user(
                    request,
                    f"Generated {len(generated_vouchers)} voucher(s) for {selected_tournament.name}.",
                    messages.SUCCESS,
                )
        else:
            form = TournamentRegistrationVoucherBulkGenerateForm()

        context = {
            **self.admin_site.each_context(request),
            "title": "Bulk generate Tournament Registration Vouchers",
            "form": form,
            "generated_vouchers": generated_vouchers,
            "selected_tournament": selected_tournament,
            "export_pdf_url": reverse(
                "admin:tournaments_tournamentregistrationvoucher_export_pdf"
            ),
        }
        return render(
            request,
            "admin/tournaments/tournamentregistrationvoucher/bulk_generate.html",
            context,
        )

    def export_pdf_view(self, request):
        """Return a simple printable PDF of one generated voucher batch."""
        raw_ids = request.GET.get("ids", "")
        try:
            voucher_ids = [int(value) for value in raw_ids.split(",") if value]
        except ValueError as exc:
            raise Http404("Invalid voucher batch.") from exc
        vouchers = list(
            TournamentRegistrationVoucher.objects.filter(pk__in=voucher_ids)
            .select_related("tournament")
            .order_by("code")
        )
        if not vouchers:
            raise Http404("Voucher batch not found.")
        tournament = vouchers[0].tournament
        if any(voucher.tournament_id != tournament.id for voucher in vouchers):
            raise Http404("A voucher export may contain one tournament only.")

        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        buffer = BytesIO()
        document = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=18 * mm,
            rightMargin=18 * mm,
            topMargin=16 * mm,
            bottomMargin=16 * mm,
        )
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            "VoucherTitle",
            parent=styles["Heading1"],
            alignment=TA_CENTER,
            fontSize=16,
            spaceAfter=6,
        )
        subtitle_style = ParagraphStyle(
            "VoucherSubtitle",
            parent=styles["BodyText"],
            alignment=TA_CENTER,
            fontSize=10,
            textColor=colors.HexColor("#444444"),
            spaceAfter=12,
        )
        uses_vary = any(voucher.usage_limit != 1 for voucher in vouchers)
        headings = ["Voucher code"] + (["Uses"] if uses_vary else [])
        rows = [headings]
        for voucher in vouchers:
            row = [voucher.code]
            if uses_vary:
                row.append(str(voucher.usage_limit or "Unlimited"))
            rows.append(row)
        column_widths = [115 * mm, 35 * mm] if uses_vary else [150 * mm]
        table = Table(rows, colWidths=column_widths, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0D6EFD")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 11),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#AAB7C4")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F7FB")]),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        generated_at = timezone.localtime().strftime("%Y-%m-%d %H:%M")
        document.build([
            Paragraph("PFC Tournament Registration Vouchers", title_style),
            Paragraph(
                f"<b>{tournament.name}</b><br/>{len(vouchers)} voucher(s) · Generated export: {generated_at}",
                subtitle_style,
            ),
            Spacer(1, 3 * mm),
            table,
        ])
        filename = f"pfc-vouchers-tournament-{tournament.id}.pdf"
        response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


@admin.register(TournamentCourt)
class TournamentCourtAdmin(admin.ModelAdmin):
    list_display = ("tournament", "court")
    list_filter = ("tournament", "court")
    search_fields = ("tournament__name", "court__number")

@admin.register(TournamentTeam)
class TournamentTeamAdmin(ActiveTeamMixin, ActiveTournamentMixin, admin.ModelAdmin):
    list_display = ("team", "tournament", "seeding_position", "is_active", "current_stage_number")
    list_filter = ("tournament", "team", "is_active", "current_stage_number")
    search_fields = ("tournament__name", "team__name")
    ordering = ("tournament", "team")
    autocomplete_fields = ["team"]


@admin.register(MeleePlayer)
class MeleePlayerAdmin(ActiveTeamMixin, ActiveTournamentMixin, MeleePlayerSwapAdminMixin, admin.ModelAdmin):
    list_display = ("player", "tournament", "registered_at", "assigned_team", "original_team", "swap_button")
    list_filter = ("tournament", "registered_at", "assigned_team")
    search_fields = ("player__name", "tournament__name", "assigned_team__name")
    readonly_fields = ("registered_at",)
    autocomplete_fields = ["player", "tournament", "assigned_team"]
    ordering = ("tournament", "registered_at")

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'player', 'tournament', 'assigned_team', 'original_team'
        )



# ── Poule / Group admin (registers PouleAdmin) ────────────────────────────────
from . import poule_admin  # noqa: F401, E402
