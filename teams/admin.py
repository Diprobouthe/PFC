from django.contrib import admin
from .models import Team, Player, TeamAvailability, PlayerProfile, TeamProfile

class PlayerInline(admin.TabularInline):
    model = Player
    extra = 0

class TeamAvailabilityInline(admin.TabularInline):
    model = TeamAvailability
    extra = 0

class TeamProfileInline(admin.StackedInline):
    model = TeamProfile
    can_delete = False
    verbose_name_plural = 'Team Profile'
    
    fieldsets = (
        ('Pictures', {
            'fields': ('logo_svg', 'team_photo_jpg'),
            'description': 'Upload team logo (SVG) and team photo (JPG)'
        }),
        ('Team Information', {
            'fields': ('description', 'motto', 'founded_date')
        }),
        ('Team Management', {
            'fields': ('profile_type', 'is_friendly_team'),
            'description': 'Configuration for team management interface'
        }),
        ('Dynamic Values & Statistics', {
            'fields': ('team_value', 'matches_played', 'matches_won', 'tournaments_participated', 'tournaments_won'),
            'classes': ('collapse',)
        }),
    )

class ProfileTypeFilter(admin.SimpleListFilter):
    """Filter teams by their TeamProfile.profile_type."""
    title = 'Profile Type'
    parameter_name = 'profile_type'

    def lookups(self, request, model_admin):
        return [
            ('full', 'Full (Public)'),
            ('minimal', 'Minimal (Hidden)'),
            ('sub_team', 'Sub-Team'),
            ('friendly', 'Friendly'),
            ('no_profile', 'No Profile'),
        ]

    def queryset(self, request, queryset):
        if self.value() == 'no_profile':
            return queryset.filter(profile__isnull=True)
        if self.value():
            return queryset.filter(profile__profile_type=self.value())
        return queryset


class HasTournamentHistoryFilter(admin.SimpleListFilter):
    """Filter teams by whether they have tournament participation history."""
    title = 'Tournament History'
    parameter_name = 'has_tournament_history'

    def lookups(self, request, model_admin):
        return [
            ('yes', 'Has tournament history (protected)'),
            ('no', 'No tournament history'),
        ]

    def queryset(self, request, queryset):
        from tournaments.models import TournamentTeam
        teams_with_history = TournamentTeam.objects.values_list('team_id', flat=True).distinct()
        if self.value() == 'yes':
            return queryset.filter(pk__in=teams_with_history)
        if self.value() == 'no':
            return queryset.exclude(pk__in=teams_with_history)
        return queryset


class ArchiveStatusFilter(admin.SimpleListFilter):
    """Filter teams by archive status: Active / Archived / All."""
    title = 'Archive Status'
    parameter_name = 'archive_status'

    def lookups(self, request, model_admin):
        return [
            ('active', 'Active (not archived)'),
            ('archived', 'Archived'),
        ]

    def queryset(self, request, queryset):
        if self.value() == 'active':
            return queryset.filter(is_archived=False)
        if self.value() == 'archived':
            return queryset.filter(is_archived=True)
        return queryset  # 'All' — no filter applied


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_archived_display', 'profile_type_display', 'is_subteam', 'parent_team',
                    'subteam_type', 'created_at', 'player_count', 'tournament_count', 'has_profile', 'is_protected')
    list_filter = (ArchiveStatusFilter, ProfileTypeFilter, HasTournamentHistoryFilter, 'is_subteam', 'subteam_type', 'created_at')
    search_fields = ('name', 'parent_team__name')
    inlines = [PlayerInline, TeamAvailabilityInline, TeamProfileInline]
    actions = ['archive_teams', 'unarchive_teams']

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'pin')
        }),
        ('Subteam Configuration', {
            'fields': ('parent_team', 'is_subteam', 'subteam_type'),
            'description': 'Configure subteam relationships. Leave blank for regular teams.'
        }),
        ('Archive', {
            'fields': ('is_archived',),
            'description': 'Archived teams are hidden from all dropdowns. Their history is preserved.'
        }),
    )

    def is_archived_display(self, obj):
        if obj.is_archived:
            return '<span style="background:#dc3545;color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;">Archived</span>'
        return '<span style="background:#28a745;color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;">Active</span>'
    is_archived_display.allow_tags = True
    is_archived_display.short_description = 'Status'
    is_archived_display.admin_order_field = 'is_archived'

    def archive_teams(self, request, queryset):
        updated = queryset.update(is_archived=True)
        self.message_user(request, f'{updated} team(s) archived. They are now hidden from all dropdowns.')
    archive_teams.short_description = 'Archive selected teams (hide from dropdowns)'

    def unarchive_teams(self, request, queryset):
        updated = queryset.update(is_archived=False)
        self.message_user(request, f'{updated} team(s) unarchived. They will appear in dropdowns again.')
    unarchive_teams.short_description = 'Unarchive selected teams (restore to dropdowns)'

    def player_count(self, obj):
        return obj.players.count()
    player_count.short_description = 'Players'

    def has_profile(self, obj):
        return hasattr(obj, 'profile')
    has_profile.boolean = True
    has_profile.short_description = 'Has Profile'

    def profile_type_display(self, obj):
        try:
            pt = obj.profile.profile_type
        except Exception:
            return '—'
        colours = {'full': '#28a745', 'minimal': '#6c757d', 'sub_team': '#17a2b8', 'friendly': '#fd7e14'}
        colour = colours.get(pt, '#6c757d')
        return f'<span style="background:{colour};color:#fff;padding:2px 7px;border-radius:10px;font-size:11px;">{pt}</span>'
    profile_type_display.allow_tags = True
    profile_type_display.short_description = 'Profile Type'
    profile_type_display.admin_order_field = 'profile__profile_type'

    def tournament_count(self, obj):
        try:
            from tournaments.models import TournamentTeam
            return TournamentTeam.objects.filter(team=obj).values('tournament').distinct().count()
        except Exception:
            return 0
    tournament_count.short_description = 'Tournaments'

    def is_protected(self, obj):
        """True if team has tournament history and should not be deleted."""
        try:
            from tournaments.models import TournamentTeam
            return TournamentTeam.objects.filter(team=obj).exists()
        except Exception:
            return False
    is_protected.boolean = True
    is_protected.short_description = 'Protected'

    def get_queryset(self, request):
        # The admin list shows ALL teams (including archived) so admins can manage them.
        # Archived teams are excluded only from dropdowns/autocomplete via get_search_results.
        return super().get_queryset(request).select_related('parent_team', 'profile')

    def get_search_results(self, request, queryset, search_term):
        """
        Called by autocomplete_fields widgets in OTHER admin classes that
        point at Team. Exclude archived teams from autocomplete results.
        """
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        if request.path.endswith('/autocomplete/'):
            queryset = queryset.filter(is_archived=False)
        return queryset, use_distinct

    def delete_model(self, request, obj):
        """Block deletion of teams that have tournament history."""
        try:
            from tournaments.models import TournamentTeam
            if TournamentTeam.objects.filter(team=obj).exists():
                from django.contrib import messages as admin_messages
                self.message_user(
                    request,
                    f'Cannot delete "{obj.name}" — it has tournament history. '
                    'Archive or reassign the team instead.',
                    level='ERROR',
                )
                return  # Do not delete
        except Exception:
            pass
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        """Block bulk deletion of teams with tournament history."""
        try:
            from tournaments.models import TournamentTeam
            protected_ids = set(
                TournamentTeam.objects.filter(team__in=queryset)
                .values_list('team_id', flat=True)
                .distinct()
            )
            if protected_ids:
                safe = queryset.exclude(pk__in=protected_ids)
                blocked_names = ', '.join(
                    queryset.filter(pk__in=protected_ids).values_list('name', flat=True)
                )
                self.message_user(
                    request,
                    f'Blocked deletion of protected teams: {blocked_names}. '
                    'Only teams without tournament history were deleted.',
                    level='WARNING',
                )
                super().delete_queryset(request, safe)
                return
        except Exception:
            pass
        super().delete_queryset(request, queryset)

class PlayerProfileInline(admin.StackedInline):
    model = PlayerProfile
    can_delete = False
    verbose_name_plural = 'Profile'

@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ('name', 'team', 'is_captain', 'created_at', 'has_profile')
    list_filter = ('team', 'is_captain')
    search_fields = ('name', 'team__name')
    inlines = [PlayerProfileInline]
    
    def has_profile(self, obj):
        return hasattr(obj, 'profile')
    has_profile.boolean = True
    has_profile.short_description = 'Has Profile'

@admin.register(PlayerProfile)
class PlayerProfileAdmin(admin.ModelAdmin):
    list_display = ('player', 'email', 'skill_level', 'rating_value', 'level_display', 'matches_played', 'matches_won', 'win_rate_display', 'rating_trend_display', 'is_active')
    list_filter = ('skill_level', 'preferred_position', 'is_active')
    search_fields = ('player__name', 'email')
    readonly_fields = ('rating_history_display', 'level_display', 'rating_trend_display', 'value', 'created_at', 'updated_at')
    
    fieldsets = (
        ('Player Information', {
            'fields': ('player', 'email', 'phone', 'date_of_birth', 'bio')
        }),
        ('Game Statistics', {
            'fields': ('skill_level', 'matches_played', 'matches_won', 'preferred_position')
        }),
        ('Dynamic Rating System', {
            'fields': ('value', 'level_display', 'rating_trend_display', 'rating_history_display'),
            'description': 'Dynamic rating system tracks player performance over time. Rating updates automatically after matches.'
        }),
        ('Media', {
            'fields': ('profile_picture',)
        }),
        ('Profile Status', {
            'fields': ('is_active',),
            'description': 'Deactivating a profile excludes the player from ratings, PFC Market, and ranking. The player record and history are preserved.'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def rating_value(self, obj):
        """Display rating value with color coding"""
        level_colors = {
            'novice': '#6c757d',      # Gray
            'intermediate': '#17a2b8', # Info blue  
            'advanced': '#007bff',     # Primary blue
            'pro': '#28a745'          # Success green
        }
        color = level_colors.get(obj.level, '#6c757d')
        return f'<span style="color: {color}; font-weight: bold;">{obj.value:.1f}</span>'
    rating_value.allow_tags = True
    rating_value.short_description = 'Rating'
    
    def level_display(self, obj):
        """Display level with badge styling"""
        level_info = obj.get_level_display()
        level_name, badge_class = level_info
        
        badge_colors = {
            'secondary': '#6c757d',
            'info': '#17a2b8', 
            'primary': '#007bff',
            'success': '#28a745'
        }
        color = badge_colors.get(badge_class, '#6c757d')
        
        return f'<span style="background-color: {color}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">{level_name}</span>'
    level_display.allow_tags = True
    level_display.short_description = 'Level'
    
    def rating_trend_display(self, obj):
        """Display rating trend with arrows"""
        trend_info = obj.get_rating_trend()
        trend = trend_info['trend']
        change = trend_info['change']
        
        if trend == 'rising':
            arrow = '📈'
            color = '#28a745'  # Green
        elif trend == 'falling':
            arrow = '📉'
            color = '#dc3545'  # Red
        else:
            arrow = '➡️'
            color = '#6c757d'  # Gray
            
        return f'<span style="color: {color};">{arrow} {change:+.1f}</span>'
    rating_trend_display.allow_tags = True
    rating_trend_display.short_description = 'Trend'
    
    def rating_history_display(self, obj):
        """Display rating history in a readable format"""
        if not obj.rating_history:
            return "No rating history yet"
        
        history_html = '<div style="max-height: 200px; overflow-y: auto;">'
        history_html += '<table style="width: 100%; font-size: 12px;">'
        history_html += '<tr style="background-color: #f8f9fa;"><th>Date</th><th>Change</th><th>New Rating</th><th>Match</th></tr>'
        
        # Show last 10 entries
        recent_history = obj.rating_history[-10:] if len(obj.rating_history) > 10 else obj.rating_history
        
        for entry in reversed(recent_history):  # Most recent first
            try:
                date = entry.get('timestamp', 'Unknown')[:10]  # Just the date part
                change = entry.get('change', 0)
                new_value = entry.get('new_value', 0)
                match_type = entry.get('match_type', 'unknown')
                match_id = entry.get('match_id', 'N/A')
                
                change_color = '#28a745' if change > 0 else '#dc3545' if change < 0 else '#6c757d'
                
                history_html += f'''
                <tr>
                    <td>{date}</td>
                    <td style="color: {change_color};">{change:+.1f}</td>
                    <td>{new_value:.1f}</td>
                    <td>{match_type} #{match_id}</td>
                </tr>
                '''
            except (KeyError, TypeError):
                continue
                
        history_html += '</table></div>'
        
        if len(obj.rating_history) > 10:
            history_html += f'<p style="font-style: italic; margin-top: 10px;">Showing last 10 of {len(obj.rating_history)} entries</p>'
            
        return history_html
    rating_history_display.allow_tags = True
    rating_history_display.short_description = 'Rating History'
    
    def win_rate_display(self, obj):
        return f"{obj.win_rate()}%"
    win_rate_display.short_description = 'Win Rate'


@admin.register(TeamProfile)
class TeamProfileAdmin(admin.ModelAdmin):
    list_display = ('team', 'profile_type', 'is_friendly_team', 'team_value', 'level_display', 'matches_played', 'matches_won', 'win_rate_display', 'has_logo', 'has_photo')
    list_filter = ('profile_type', 'is_friendly_team', 'founded_date')
    search_fields = ('team__name', 'description', 'motto')
    readonly_fields = ('team_value_display', 'level_display', 'value_history_display', 'badge_display', 'created_at', 'updated_at')
    
    fieldsets = (
        ('Team Information', {
            'fields': ('team', 'profile_type', 'is_friendly_team')
        }),
        ('Pictures', {
            'fields': ('logo_svg', 'team_photo_jpg'),
            'description': 'Upload team logo (SVG) and team photo (JPG)'
        }),
        ('Team Details', {
            'fields': ('description', 'motto', 'founded_date')
        }),
        ('Dynamic Values & Statistics', {
            'fields': ('team_value_display', 'level_display', 'matches_played', 'matches_won', 'tournaments_participated', 'tournaments_won'),
            'description': 'Team rating and performance statistics'
        }),
        ('Badges & Achievements', {
            'fields': ('badge_display',),
            'classes': ('collapse',),
            'description': 'Team achievements and earned badges'
        }),
        ('History & Tracking', {
            'fields': ('value_history_display', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def team_value_display(self, obj):
        """Display team value with color coding"""
        level_colors = {
            'developing': '#6c757d',    # Gray
            'competitive': '#17a2b8',  # Info blue  
            'elite': '#007bff',        # Primary blue
            'champion': '#28a745'      # Success green
        }
        color = level_colors.get(obj.level, '#6c757d')
        return f'<span style="color: {color}; font-weight: bold;">{obj.team_value:.1f}</span>'
    team_value_display.allow_tags = True
    team_value_display.short_description = 'Team Value'
    
    def level_display(self, obj):
        """Display level with badge styling"""
        level_info = obj.get_level_display()
        level_name, badge_class = level_info
        
        badge_colors = {
            'secondary': '#6c757d',
            'info': '#17a2b8', 
            'primary': '#007bff',
            'success': '#28a745'
        }
        color = badge_colors.get(badge_class, '#6c757d')
        
        return f'<span style="background-color: {color}; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: bold;">{level_name}</span>'
    level_display.allow_tags = True
    level_display.short_description = 'Level'
    
    def win_rate_display(self, obj):
        return f"{obj.win_rate()}%"
    win_rate_display.short_description = 'Win Rate'
    
    def has_logo(self, obj):
        return bool(obj.logo_svg)
    has_logo.boolean = True
    has_logo.short_description = 'Logo'
    
    def has_photo(self, obj):
        return bool(obj.team_photo_jpg)
    has_photo.boolean = True
    has_photo.short_description = 'Photo'
    
    def value_history_display(self, obj):
        """Display team value history in a readable format"""
        if not obj.value_history:
            return "No value history yet"
        
        history_html = '<div style="max-height: 200px; overflow-y: auto;">'
        history_html += '<table style="width: 100%; font-size: 12px;">'
        history_html += '<tr style="background-color: #f8f9fa;"><th>Date</th><th>Change</th><th>New Value</th><th>Reason</th></tr>'
        
        # Show last 10 entries
        recent_history = obj.value_history[-10:] if len(obj.value_history) > 10 else obj.value_history
        
        for entry in reversed(recent_history):  # Most recent first
            try:
                date = entry.get('timestamp', 'Unknown')[:10]  # Just the date part
                change = entry.get('change', 0)
                new_value = entry.get('new_value', 0)
                reason = entry.get('reason', 'unknown')
                
                change_color = '#28a745' if change > 0 else '#dc3545' if change < 0 else '#6c757d'
                
                history_html += f'''
                <tr>
                    <td>{date}</td>
                    <td style="color: {change_color};">{change:+.1f}</td>
                    <td>{new_value:.1f}</td>
                    <td>{reason.replace('_', ' ').title()}</td>
                </tr>
                '''
            except (KeyError, TypeError):
                continue
                
        history_html += '</table></div>'
        
        if len(obj.value_history) > 10:
            history_html += f'<p style="font-style: italic; margin-top: 10px;">Showing last 10 of {len(obj.value_history)} entries</p>'
            
        return history_html
    value_history_display.allow_tags = True
    value_history_display.short_description = 'Value History'
    
    def badge_display(self, obj):
        """Display team badges in a readable format"""
        badges = obj.get_badge_display()
        if not badges:
            return "No badges earned yet"
        
        badge_html = '<div style="max-height: 150px; overflow-y: auto;">'
        
        for badge in badges:
            badge_html += f'''
            <div style="margin-bottom: 8px; padding: 4px; border-left: 3px solid #007bff;">
                <strong>{badge['display_name']}</strong><br>
                <small style="color: #6c757d;">Earned: {badge['earned_at'][:10] if badge['earned_at'] else 'Unknown'}</small>
            </div>
            '''
        
        badge_html += '</div>'
        return badge_html
    badge_display.allow_tags = True
    badge_display.short_description = 'Badges'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('team')
    
    def has_change_permission(self, request, obj=None):
        """
        Implement access control logic:
        - If team has captain: only captain can edit
        - If team has no captain: any team player can edit
        - Staff can always edit
        """
        if request.user.is_staff or request.user.is_superuser:
            return True
        
        if obj is None:  # Creating new profile
            return True
        
        # Check if user is a player in this team
        try:
            # Get the player associated with this user (assuming user has a player profile)
            user_player = None
            
            # Try to find player by matching user info (this depends on your user-player relationship)
            # For now, we'll implement a basic check - you may need to adjust based on your auth system
            
            # Check if any player in the team matches the current user
            team_players = obj.team.players.all()
            
            # If team has a captain, only captain can edit
            captain = team_players.filter(is_captain=True).first()
            if captain:
                # Only captain can edit (you'll need to implement user-player matching)
                # For now, return True - implement proper user-player matching later
                return True
            else:
                # No captain - any team player can edit
                # For now, return True - implement proper user-player matching later
                return True
                
        except Exception:
            # If anything goes wrong, default to staff-only access
            return request.user.is_staff
    
    def has_delete_permission(self, request, obj=None):
        """Same access control for deletion"""
        return self.has_change_permission(request, obj)

