from django.contrib import admin
from django.contrib import messages
from django.utils.html import format_html
from .models import Tournament, TournamentTeam, Round, Bracket, TournamentCourt, Stage, MeleePlayer
from .admin_helpers import (
    retry_automation_action,
    advance_stage_action, 
    generate_round_action,
    reset_automation_status_action,
    get_tournament_debug_info
)
from .admin_actions import complete_and_assign_badges, reset_automation_status

# --- Inlines --- 

class StageInline(admin.TabularInline):
    """Inline editor for defining stages within a multi-stage tournament"""
    model = Stage
    extra = 0  # Don't auto-create empty stages that break match generation
    fields = ("stage_number", "name", "format", "num_rounds_in_stage", "num_qualifiers", "num_matches_per_team")
    ordering = ["stage_number"]

class TournamentTeamInline(admin.TabularInline):
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
    readonly_fields = ("number", "stage", "number_in_stage")
    ordering = ["number"]

# --- Model Admins --- 

@admin.register(Tournament)
class TournamentAdmin(admin.ModelAdmin):
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
        "actions_display"
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
            "fields": ("name", "format")
        }),
        ("Play Formats", {
            "fields": ("has_triplets", "has_doublets", "has_tete_a_tete")
        }),
        ("Mêlée Mode", {
            "fields": ("is_melee", "melee_format", "melee_teams_generated", "max_participants"),
            "classes": ("collapse",),
            "description": "Enable Mêlée mode for individual player registration with automatic team generation"
        }),
        ("Dates", {
            "fields": ("start_date", "end_date")
        }),
        ("Status", {
            "fields": ("is_active", "is_archived", "current_round_number")
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
            "fields": ("default_time_limit_minutes",),
            "classes": ("collapse",),
            "description": "Set default time limit for all matches in this tournament. Timer starts when both teams activate the match."
        }),
    )
    actions = [
        "make_active", 
        "archive_tournaments", 
        "generate_matches", 
        "advance_knockout_tournaments",
        retry_automation_action,
        advance_stage_action,
        generate_round_action,
        reset_automation_status_action,
        complete_and_assign_badges,
        reset_automation_status,
        "generate_melee_teams_random",
        "generate_melee_teams_balanced",
        "generate_melee_teams_snake_draft",
        "restore_melee_players_to_original_teams",
    ]
    
    def get_inlines(self, request, obj=None):
        inlines = [TournamentTeamInline, TournamentCourtInline]
        if obj and obj.is_multi_stage:
            inlines.append(StageInline)
        inlines.append(RoundInline)
        return inlines

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
    
    def actions_display(self, obj):
        buttons = []
        if obj.is_active and not obj.is_archived:
            buttons.append(format_html("<a class=\"button\" href=\"/admin/tournaments/tournament/{}/generate-matches/\">Generate Matches</a>", obj.id))
        return format_html("&nbsp;".join(buttons))
    actions_display.short_description = "Quick Actions"
    actions_display.allow_tags = True
    
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

@admin.register(Stage)
class StageAdmin(admin.ModelAdmin):
    list_display = ("tournament", "stage_number", "name", "format", "num_rounds_in_stage", "num_qualifiers", "num_matches_per_team", "is_complete")
    list_filter = ("tournament", "format", "is_complete")
    search_fields = ("tournament__name", "name")
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
            "description": "For Round Robin stages only: specify number of matches per team for Incomplete Round Robin. Leave blank for full Round Robin where every team plays every other team."
        }),
        ("Status", {
            "fields": ("is_complete",)
        }),
    )

@admin.register(Round)
class RoundAdmin(admin.ModelAdmin):
    list_display = ("__str__", "tournament", "stage", "number", "number_in_stage", "match_count", "is_complete")
    list_filter = ("tournament", "stage", "is_complete")
    search_fields = ("tournament__name", "stage__name")
    readonly_fields = ("tournament", "stage", "number", "number_in_stage")
    ordering = ("tournament", "number")
    
    def match_count(self, obj):
        count = obj.matches.count()
        return format_html("<a href=\"/admin/matches/match/?round__id__exact={}\">{} matches</a>", obj.id, count)
    match_count.short_description = "Matches"

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

@admin.register(TournamentCourt)
class TournamentCourtAdmin(admin.ModelAdmin):
    list_display = ("tournament", "court")
    list_filter = ("tournament", "court")
    search_fields = ("tournament__name", "court__number")

@admin.register(TournamentTeam)
class TournamentTeamAdmin(admin.ModelAdmin):
    list_display = ("team", "tournament", "seeding_position", "is_active", "current_stage_number")
    list_filter = ("tournament", "team", "is_active", "current_stage_number")
    search_fields = ("tournament__name", "team__name")
    ordering = ("tournament", "team")
    autocomplete_fields = ["team"]


@admin.register(MeleePlayer)
class MeleePlayerAdmin(admin.ModelAdmin):
    list_display = ("player", "tournament", "registered_at", "assigned_team")
    list_filter = ("tournament", "registered_at", "assigned_team")
    search_fields = ("player__name", "tournament__name", "assigned_team__name")
    readonly_fields = ("registered_at",)
    autocomplete_fields = ["player", "tournament", "assigned_team"]
    ordering = ("tournament", "registered_at")
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('player', 'tournament', 'assigned_team')

