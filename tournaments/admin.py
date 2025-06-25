from django.contrib import admin
from django.contrib import messages
from django.utils.html import format_html
from .models import Tournament, TournamentTeam, Round, Bracket, TournamentCourt, Stage

# --- Inlines --- 

class StageInline(admin.TabularInline):
    """Inline editor for defining stages within a multi-stage tournament"""
    model = Stage
    extra = 0  # Don't auto-create empty stages that break match generation
    fields = ("stage_number", "name", "format", "num_rounds_in_stage", "num_qualifiers")
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
        ("Dates", {
            "fields": ("start_date", "end_date")
        }),
        ("Status", {
            "fields": ("is_active", "is_archived")
        }),
        ("Description", {
            "fields": ("description",),
            "classes": ("collapse",)
        }),
    )
    actions = ["make_active", "archive_tournaments", "generate_matches", "advance_knockout_tournaments"]
    
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

@admin.register(Stage)
class StageAdmin(admin.ModelAdmin):
    list_display = ("tournament", "stage_number", "name", "format", "num_rounds_in_stage", "num_qualifiers", "is_complete")
    list_filter = ("tournament", "format", "is_complete")
    search_fields = ("tournament__name", "name")
    ordering = ("tournament", "stage_number")

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
