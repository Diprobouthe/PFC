from django import forms
from django.core.exceptions import ValidationError
from .models import Tournament, TournamentTeam
from teams.models import Team
from teams.subteam_service import get_subteam_manager


class SubteamRegistrationForm(forms.Form):
    """
    Enhanced form for team registration with subteam functionality
    """
    
    def __init__(self, tournament, team, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tournament = tournament
        self.team = team
        self.subteam_manager = get_subteam_manager(team)
        
        # Get tournament format restrictions
        self.allowed_formats = self._get_allowed_formats()
        
        # Create dynamic fields based on tournament format
        self._create_subteam_fields()
        
        # Add existing subteam information
        self._add_existing_subteam_info()
    
    def _get_allowed_formats(self):
        """Get allowed formats from tournament configuration"""
        formats = []
        
        # Check tournament format restrictions
        if getattr(self.tournament, 'has_triplets', False):
            formats.append('triplet')
        if getattr(self.tournament, 'has_doublets', False):
            formats.append('doublette')
        if getattr(self.tournament, 'has_tete_a_tete', False):
            formats.append('tete_a_tete')
        
        # If no specific formats are set, check the play_format field
        if not formats:
            play_format = getattr(self.tournament, 'play_format', '')
            if play_format == 'triplets':
                formats = ['triplet']
            elif play_format == 'doublets':
                formats = ['doublette']
            elif play_format == 'tete_a_tete':
                formats = ['tete_a_tete']
            elif play_format == 'mixed':
                formats = ['triplet', 'doublette', 'tete_a_tete']
            else:
                # Default fallback - but this should not happen in a well-configured tournament
                formats = ['triplet']
        
        return formats
    
    def _create_subteam_fields(self):
        """Create dynamic fields for each allowed format"""
        for format_type in self.allowed_formats:
            # Count field
            count_field_name = f'{format_type}_count'
            max_possible = self.team.players.count() // self._get_players_per_format(format_type)
            
            self.fields[count_field_name] = forms.IntegerField(
                label=f'Number of {format_type.replace("_", "-").title()}s',
                min_value=0,
                max_value=max_possible,
                initial=0,
                required=False,
                help_text=f'Maximum possible: {max_possible} (you have {self.team.players.count()} players)'
            )
            
            # Reuse existing field
            reuse_field_name = f'{format_type}_reuse'
            existing_count = self.subteam_manager.get_existing_subteams(format_type).count()
            
            if existing_count > 0:
                self.fields[reuse_field_name] = forms.BooleanField(
                    label=f'Reuse existing {format_type.replace("_", "-").title()}s',
                    initial=True,
                    required=False,
                    help_text=f'You have {existing_count} existing {format_type}(s) that can be reused'
                )
    
    def _add_existing_subteam_info(self):
        """Add information about existing subteams"""
        self.existing_subteams = {}
        for format_type in self.allowed_formats:
            existing = self.subteam_manager.get_existing_subteams(format_type)
            self.existing_subteams[format_type] = list(existing)
    
    def _get_players_per_format(self, format_type):
        """Get number of players required per format"""
        format_map = {
            'triplet': 3,
            'doublette': 2,
            'tete_a_tete': 1
        }
        return format_map.get(format_type, 3)
    
    def clean(self):
        """Validate the form data"""
        cleaned_data = super().clean()
        
        # Check tournament format restrictions first
        if not self.allowed_formats:
            raise ValidationError(
                f"This tournament ({self.tournament.name}) has no valid formats configured. "
                "Please contact the tournament administrator."
            )
        
        # Check if at least one subteam is requested
        total_subteams = 0
        subteam_specs = []
        
        for format_type in self.allowed_formats:
            count_field = f'{format_type}_count'
            count = cleaned_data.get(count_field, 0)
            
            if count > 0:
                total_subteams += count
                reuse_field = f'{format_type}_reuse'
                reuse_existing = cleaned_data.get(reuse_field, True)
                
                subteam_specs.append({
                    'type': format_type,
                    'count': count,
                    'reuse_existing': reuse_existing
                })
        
        if total_subteams == 0:
            allowed_format_names = [f.replace('_', '-').title() for f in self.allowed_formats]
            raise ValidationError(
                f"Please specify at least one subteam to register for the tournament. "
                f"This tournament allows: {', '.join(allowed_format_names)}"
            )
        
        # Validate with subteam manager
        validation = self.subteam_manager.validate_subteam_request(subteam_specs)
        if not validation['valid']:
            raise ValidationError(validation['errors'])
        
        # Additional tournament-specific validation
        self._validate_tournament_restrictions(subteam_specs)
        
        cleaned_data['subteam_specs'] = subteam_specs
        cleaned_data['total_subteams'] = total_subteams
        
        return cleaned_data
    
    def _validate_tournament_restrictions(self, subteam_specs):
        """Validate subteam specs against tournament restrictions"""
        errors = []
        
        # Check if tournament has maximum team limits
        max_teams = getattr(self.tournament, 'max_teams', None)
        if max_teams:
            current_teams = self.tournament.teams.count()
            requested_teams = sum(spec['count'] for spec in subteam_specs)
            
            if current_teams + requested_teams > max_teams:
                errors.append(
                    f"Tournament is limited to {max_teams} teams. "
                    f"Currently has {current_teams} teams, you're requesting {requested_teams} more."
                )
        
        # Check format-specific restrictions
        for spec in subteam_specs:
            format_type = spec['type']
            count = spec['count']
            
            # Validate against tournament format settings
            if format_type == 'triplet' and not getattr(self.tournament, 'has_triplets', False):
                if self.tournament.play_format != 'triplets' and self.tournament.play_format != 'mixed':
                    errors.append(f"This tournament does not allow triplet format.")
            
            elif format_type == 'doublette' and not getattr(self.tournament, 'has_doublets', False):
                if self.tournament.play_format != 'doublets' and self.tournament.play_format != 'mixed':
                    errors.append(f"This tournament does not allow doublette format.")
            
            elif format_type == 'tete_a_tete' and not getattr(self.tournament, 'has_tete_a_tete', False):
                if self.tournament.play_format != 'tete_a_tete' and self.tournament.play_format != 'mixed':
                    errors.append(f"This tournament does not allow tête-à-tête format.")
        
        if errors:
            raise ValidationError(errors)
    
    def save(self):
        """Create subteams and register them for the tournament"""
        subteam_specs = self.cleaned_data['subteam_specs']
        
        # Create subteams using the subteam manager
        result = self.subteam_manager.create_subteams(
            subteam_specs, 
            auto_register_tournament=self.tournament
        )
        
        return result


class QuickTeamRegistrationForm(forms.Form):
    """
    Quick registration form for teams that don't need subteams
    """
    team_pin = forms.CharField(
        max_length=6,
        widget=forms.TextInput(attrs={
            'placeholder': 'Enter your 6-digit team PIN',
            'class': 'form-control team-pin-field',
            'pattern': '[0-9]{6}',
            'title': 'Please enter a 6-digit PIN',
            'autocomplete': 'off'
        }),
        help_text='Enter your team PIN to register for this tournament'
    )
    
    def __init__(self, tournament, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tournament = tournament
        self.team = None
    
    def clean_team_pin(self):
        """Validate team PIN and get team"""
        pin = self.cleaned_data['team_pin']
        
        try:
            self.team = Team.objects.get(pin=pin)
        except Team.DoesNotExist:
            raise ValidationError("Invalid team PIN. Please check and try again.")
        
        # Check if team is already registered
        if TournamentTeam.objects.filter(tournament=self.tournament, team=self.team).exists():
            raise ValidationError(f"Team '{self.team.name}' is already registered for this tournament.")
        
        # Check if team size is compatible with tournament format
        self._validate_team_tournament_compatibility()
        
        return pin
    
    def _validate_team_tournament_compatibility(self):
        """Validate that team can participate in tournament format"""
        team_size = self.team.players.count()
        
        # Get tournament format requirements
        has_triplets = getattr(self.tournament, 'has_triplets', False)
        has_doublets = getattr(self.tournament, 'has_doublets', False)
        has_tete_a_tete = getattr(self.tournament, 'has_tete_a_tete', False)
        
        # Check based on play_format if boolean flags are not set
        play_format = getattr(self.tournament, 'play_format', '')
        if not any([has_triplets, has_doublets, has_tete_a_tete]):
            if play_format == 'triplets':
                has_triplets = True
            elif play_format == 'doublets':
                has_doublets = True
            elif play_format == 'tete_a_tete':
                has_tete_a_tete = True
            elif play_format == 'mixed':
                has_triplets = has_doublets = has_tete_a_tete = True
        
        # Validate team size against tournament requirements
        errors = []
        
        if has_triplets and not has_doublets and not has_tete_a_tete:
            # Triplets only tournament
            if team_size < 3:
                errors.append(f"This tournament requires triplets (3 players). Your team has only {team_size} players.")
            elif team_size > 3:
                errors.append(
                    f"This tournament is for triplets only. Your team has {team_size} players. "
                    "Consider using subteam registration to create multiple triplets."
                )
        
        elif has_doublets and not has_triplets and not has_tete_a_tete:
            # Doublettes only tournament
            if team_size < 2:
                errors.append(f"This tournament requires doublettes (2 players). Your team has only {team_size} players.")
            elif team_size > 2:
                errors.append(
                    f"This tournament is for doublettes only. Your team has {team_size} players. "
                    "Consider using subteam registration to create multiple doublettes."
                )
        
        elif has_tete_a_tete and not has_triplets and not has_doublets:
            # Tête-à-tête only tournament
            if team_size > 1:
                errors.append(
                    f"This tournament is for individual players only. Your team has {team_size} players. "
                    "Consider using subteam registration to register individual players."
                )
        
        # For mixed tournaments, we're more lenient but still provide guidance
        elif team_size < 1:
            errors.append("Your team must have at least 1 player to register.")
        
        if errors:
            raise ValidationError(errors)
    
    def save(self):
        """Register the team for the tournament"""
        tournament_team = TournamentTeam.objects.create(
            tournament=self.tournament,
            team=self.team
        )
        return tournament_team

