from django.contrib import admin
from django.contrib import messages # Import messages
from django.utils.html import format_html
from .models import Tournament, TournamentTeam, Round, Bracket, TournamentCourt, Stage # Import Stage

# --- Inlines --- 

class StageInline(admin.TabularInline):
    """Inline editor for defining stages within a multi-stage tournament"""
    model = Stage
    extra = 1
    fields = ("stage_number", "name", "format", "num_rounds_in_stage", "num_qualifiers")
    ordering = ["stage_number"]
    # Add verbose_name_plural if needed

class TournamentTeamInline(admin.TabularInline):
    model = TournamentTeam
    extra = 1
    autocomplete_fields = ["team"]
    # Add fields for multi-stage tracking
    # Removed notes and registration_date as they are not in the model
    fields = ("team", "seeding_position", "is_active", "current_stage_number") 
    # readonly_fields = ("registered_at",) # registered_at is auto_now_add

class TournamentCourtInline(admin.TabularInline):
    model = TournamentCourt
    extra = 1
    # autocomplete_fields = ["court"] # Keep commented out

class RoundInline(admin.TabularInline):
    model = Round
    extra = 0
    fields = ("number", "stage", "number_in_stage", "is_completed")
    readonly_fields = ("number", "stage", "number_in_stage") # Make these read-only in the inline
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
        "is_multi_stage", # Add filter for multi-stage
        "has_triplets", 
        "has_doublets", 
        "has_tete_a_tete", 
        "is_active", 
        "is_archived", 
        "start_date"
    )
    search_fields = ("name", "description")
    date_hierarchy = "start_date"
    # Dynamically set inlines based on format/is_multi_stage
    # inlines = [TournamentTeamInline, TournamentCourtInline, RoundInline, StageInline]
    fieldsets = (
        (None, {
            "fields": ("name", "format") # is_multi_stage is set automatically
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
    actions = ["make_active", "archive_tournaments", "generate_matches"]
    
    # Override get_inlines to conditionally show StageInline
    def get_inlines(self, request, obj=None):
        inlines = [TournamentTeamInline, TournamentCourtInline]
        if obj and obj.is_multi_stage:
            inlines.append(StageInline)
        # Always show rounds for now, might refine later
        inlines.append(RoundInline)
        return inlines

    # Override get_fieldsets to conditionally show fields if needed (optional)
    # def get_fieldsets(self, request, obj=None):
    #     fieldsets = super().get_fieldsets(request, obj)
    #     # Modify fieldsets based on obj.is_multi_stage if necessary
    #     return fieldsets

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
        # Link might need adjustment if admin URL changes
        return format_html("<a href=\"?tournament__id__exact={}\">{} teams</a>", obj.id, count)
    team_count.short_description = "Teams"
    
    def court_count(self, obj):
        count = obj.courts.count()
        # Link might need adjustment
        return format_html("<a href=\"?tournament__id__exact={}\">{} courts</a>", obj.id, count)
    court_count.short_description = "Courts"
    
    def actions_display(self, obj):
        buttons = []
        # Adjust URL if admin URLs change
        # Consider adding actions specific to multi-stage tournaments
        if obj.is_active and not obj.is_archived:
            # Check if matches exist before showing generate button?
            buttons.append(format_html("<a class=\"button\" href=\"/admin/tournaments/tournament/{}/generate-matches/\">Generate Matches</a>", obj.id))
        # Add button to advance stage?
        # if obj.is_multi_stage and obj.is_active and not obj.is_archived:
        #     buttons.append(format_html("<a class=\"button\" href=\"/admin/tournaments/tournament/{}/advance-stage/\">Advance Stage</a>", obj.id))
        return format_html("&nbsp;".join(buttons))
    actions_display.short_description = "Quick Actions"
    actions_display.allow_tags = True # Necessary for format_html
    
    def make_active(self, request, queryset):
        queryset.update(is_active=True, is_archived=False)
    make_active.short_description = "Mark selected tournaments as active"
    
    def archive_tournaments(self, request, queryset):
        queryset.update(is_active=False, is_archived=True)
    archive_tournaments.short_description = "Archive selected tournaments"
    
    def generate_matches(self, request, queryset):
        generated_count = 0
        error_count = 0
        for tournament in queryset:
            try:
                tournament.generate_matches() # Call the updated method
                generated_count += 1
            except Exception as e:
                # Log the error e
                error_count += 1
                # Use messages.ERROR instead of admin.ERROR
                self.message_user(request, f"Error generating matches for {tournament.name}: {e}", level=messages.ERROR) 
        
        if generated_count > 0:
            self.message_user(request, f"Generated matches for {generated_count} tournaments.")
        if error_count > 0:
             # Use messages.ERROR instead of admin.ERROR
             self.message_user(request, f"Failed to generate matches for {error_count} tournaments.", level=messages.ERROR)
             
    generate_matches.short_description = "Generate matches for selected tournaments"

@admin.register(Stage)
class StageAdmin(admin.ModelAdmin):
    list_display = ("tournament", "stage_number", "name", "format", "num_rounds_in_stage", "num_qualifiers", "is_complete")
    list_filter = ("tournament", "format", "is_complete")
    search_fields = ("tournament__name", "name")
    ordering = ("tournament", "stage_number")

@admin.register(Round)
class RoundAdmin(admin.ModelAdmin):
    list_display = ("__str__", "tournament", "stage", "number", "number_in_stage", "match_count", "is_completed") # Use __str__ for better display
    list_filter = ("tournament", "stage", "is_completed")
    search_fields = ("tournament__name", "stage__name")
    readonly_fields = ("tournament", "stage", "number", "number_in_stage")
    ordering = ("tournament", "number")
    
    def match_count(self, obj):
        count = obj.matches.count()
        # Adjust link for admin filtering
        return format_html("<a href=\"/admin/matches/match/?round__id__exact={}\">{} matches</a>", obj.id, count)
    match_count.short_description = "Matches"

@admin.register(Bracket)
class BracketAdmin(admin.ModelAdmin):
    # Corrected list_display, list_filter, readonly_fields, search_fields
    list_display = ("__str__", "tournament", "get_stage_display", "round", "position") 
    list_filter = ("tournament", "round__stage", "round")
    search_fields = ("tournament__name", "round__stage__name")
    readonly_fields = ("tournament", "round") # Removed stage
    ordering = ("tournament", "round__number", "position")

    # Method to display stage information
    def get_stage_display(self, obj):
        if obj.round and obj.round.stage:
            return f"Stage {obj.round.stage.stage_number}"
        return "N/A" # Or None, or handle single-stage tournaments
    get_stage_display.short_description = "Stage"
    get_stage_display.admin_order_field = "round__stage__stage_number" # Allow sorting

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

