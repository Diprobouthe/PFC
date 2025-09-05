from django.contrib import admin
from django.utils.html import format_html
from .models import Match, MatchActivation, MatchResult, NextOpponentRequest

class MatchActivationInline(admin.TabularInline):
    model = MatchActivation
    extra = 0
    readonly_fields = ['activated_at']

class MatchResultInline(admin.TabularInline):
    model = MatchResult
    extra = 0
    readonly_fields = ['submitted_at', 'validated_at']

@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    list_display = ('id', 'tournament', 'team1', 'team2', 'status_badge', 'score_display', 'court_display', 'timing_display', 'actions_display')
    list_filter = ('status', 'tournament', 'round', 'start_time')
    search_fields = ('team1__name', 'team2__name', 'tournament__name')
    date_hierarchy = 'start_time'
    inlines = [MatchActivationInline, MatchResultInline]
    fieldsets = (
        (None, {
            'fields': ('tournament', 'round', 'bracket')
        }),
        ('Teams', {
            'fields': ('team1', 'team2')
        }),
        ('Status', {
            'fields': ('status',)
        }),
        ('Scores', {
            'fields': ('team1_score', 'team2_score')
        }),
        ('Timing', {
            'fields': ('start_time', 'end_time', 'duration')
        }),
    )
    actions = ['mark_as_pending', 'mark_as_active', 'mark_as_completed', 'assign_courts']
    
    def status_badge(self, obj):
        if obj.status == 'pending':
            return format_html('<span style="background-color: #FFC107; padding: 3px 8px; border-radius: 10px; color: #000;">Pending</span>')
        elif obj.status == 'pending_verification':
            return format_html('<span style="background-color: #FF9800; padding: 3px 8px; border-radius: 10px; color: #000;">Partially Activated</span>')
        elif obj.status == 'active':
            return format_html('<span style="background-color: #28A745; padding: 3px 8px; border-radius: 10px; color: #fff;">Active</span>')
        elif obj.status == 'waiting_validation':
            return format_html('<span style="background-color: #17A2B8; padding: 3px 8px; border-radius: 10px; color: #fff;">Waiting Validation</span>')
        elif obj.status == 'completed':
            return format_html('<span style="background-color: #007BFF; padding: 3px 8px; border-radius: 10px; color: #fff;">Completed</span>')
        else:
            return obj.status
    status_badge.short_description = "Status"
    
    def score_display(self, obj):
        if obj.team1_score is not None and obj.team2_score is not None:
            return format_html('<strong>{}</strong> - <strong>{}</strong>', obj.team1_score, obj.team2_score)
        return "No score"
    score_display.short_description = "Score"
    
    def court_display(self, obj):
        if obj.court:
            return format_html('<a href="/admin/courts/court/{}/change/">{}</a>', 
                              obj.court.id, obj.court.number)
        return "Not assigned"
    court_display.short_description = "Court"
    
    def timing_display(self, obj):
        if obj.start_time and obj.end_time:
            duration = obj.duration or "N/A"
            return format_html('{}m', duration)
        elif obj.start_time:
            return "In progress"
        return "Not started"
    timing_display.short_description = "Duration"
    
    def actions_display(self, obj):
        buttons = []
        if obj.status == 'pending':
            buttons.append(format_html('<a class="button" href="/admin/matches/match/{}/activate/">Activate</a>', obj.id))
        elif obj.status == 'pending_verification':
            buttons.append(format_html('<a class="button" href="/admin/matches/match/{}/complete-activation/">Complete Activation</a>', obj.id))
        elif obj.status == 'active':
            buttons.append(format_html('<a class="button" href="/admin/matches/match/{}/complete/">Complete</a>', obj.id))
        elif obj.status == 'waiting_validation':
            buttons.append(format_html('<a class="button" href="/admin/matches/match/{}/validate/">Validate</a>', obj.id))
        return format_html('&nbsp;'.join(buttons))
    actions_display.short_description = "Quick Actions"
    
    def mark_as_pending(self, request, queryset):
        queryset.update(status='pending')
    mark_as_pending.short_description = "Mark selected matches as pending"
    
    def mark_as_active(self, request, queryset):
        queryset.update(status='active')
    mark_as_active.short_description = "Mark selected matches as active"
    
    def mark_as_completed(self, request, queryset):
        queryset.update(status='completed')
    mark_as_completed.short_description = "Mark selected matches as completed"
    
    def assign_courts(self, request, queryset):
        selected = queryset.count()
        self.message_user(request, f"Court assignment initiated for {selected} matches. Please select courts on the next page.")
        # In a real implementation, this would redirect to a court assignment view
    assign_courts.short_description = "Assign courts to selected matches"

@admin.register(MatchActivation)
class MatchActivationAdmin(admin.ModelAdmin):
    list_display = ('match', 'team', 'activated_at')
    list_filter = ('activated_at', 'team')
    search_fields = ('match__team1__name', 'match__team2__name', 'team__name')
    readonly_fields = ['activated_at']

@admin.register(MatchResult)
class MatchResultAdmin(admin.ModelAdmin):
    list_display = ('match', 'submitted_by', 'validated_by', 'submitted_at', 'validated_at')
    list_filter = ('submitted_at', 'validated_at')
    search_fields = ('match__team1__name', 'match__team2__name', 'submitted_by__name', 'validated_by__name')
    readonly_fields = ['submitted_at', 'validated_at']

@admin.register(NextOpponentRequest)
class NextOpponentRequestAdmin(admin.ModelAdmin):
    list_display = ('tournament', 'requesting_team', 'target_team', 'status_badge', 'created_at', 'actions_display')
    list_filter = ('status', 'tournament', 'created_at')
    search_fields = ('requesting_team__name', 'target_team__name', 'tournament__name')
    readonly_fields = ['created_at']
    actions = ['mark_as_accepted', 'mark_as_rejected']
    
    def status_badge(self, obj):
        if obj.status == 'pending':
            return format_html('<span style="background-color: #FFC107; padding: 3px 8px; border-radius: 10px; color: #000;">Pending</span>')
        elif obj.status == 'accepted':
            return format_html('<span style="background-color: #28A745; padding: 3px 8px; border-radius: 10px; color: #fff;">Accepted</span>')
        elif obj.status == 'rejected':
            return format_html('<span style="background-color: #DC3545; padding: 3px 8px; border-radius: 10px; color: #fff;">Rejected</span>')
        else:
            return obj.status
    status_badge.short_description = "Status"
    
    def actions_display(self, obj):
        buttons = []
        if obj.status == 'pending':
            buttons.append(format_html('<a class="button" href="/admin/matches/nextopponentrequest/{}/accept/">Accept</a>', obj.id))
            buttons.append(format_html('<a class="button" href="/admin/matches/nextopponentrequest/{}/reject/">Reject</a>', obj.id))
        return format_html('&nbsp;'.join(buttons))
    actions_display.short_description = "Quick Actions"
    
    def mark_as_accepted(self, request, queryset):
        queryset.update(status='accepted')
    mark_as_accepted.short_description = "Mark selected requests as accepted"
    
    def mark_as_rejected(self, request, queryset):
        queryset.update(status='rejected')
    mark_as_rejected.short_description = "Mark selected requests as rejected"
