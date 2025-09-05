from django import forms
from django.core.exceptions import ValidationError
from .models import Tournament, TournamentTeam, Stage
from teams.models import Team

class TournamentForm(forms.ModelForm):
    """Form for creating and editing tournaments"""
    class Meta:
        model = Tournament
        # Remove number_of_rounds as it was removed from the model
        fields = [
            "name", "description", "format", 
            "has_triplets", "has_doublets", "has_tete_a_tete", # Use these instead of play_format directly
            "is_melee", "melee_format",  # Add Mêlée mode fields
            "start_date", "end_date",
            "banner_enabled", "banner_image", "banner_target_url", "banner_alt_text"  # Add banner fields
        ]
        widgets = {
            "start_date": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "end_date": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "description": forms.Textarea(attrs={"rows": 4}),
            "is_melee": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "melee_format": forms.Select(attrs={"class": "form-select"}),
            "banner_enabled": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "banner_image": forms.FileInput(attrs={"class": "form-control", "accept": "image/jpeg,image/png,image/svg+xml"}),
            "banner_target_url": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://example.com"}),
            "banner_alt_text": forms.TextInput(attrs={"class": "form-control", "placeholder": "Banner description for accessibility"}),
            # Use CheckboxSelectMultiple for boolean fields if desired
            # "has_triplets": forms.CheckboxInput(), 
            # "has_doublets": forms.CheckboxInput(),
            # "has_tete_a_tete": forms.CheckboxInput(),
        }
        # Ensure play_format is set automatically in the model's save method
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add JavaScript to show/hide melee_format based on is_melee
        self.fields['melee_format'].widget.attrs.update({
            'style': 'display: none;' if not self.instance.is_melee else ''
        })
        
    def clean(self):
        cleaned_data = super().clean()
        is_melee = cleaned_data.get('is_melee')
        melee_format = cleaned_data.get('melee_format')
        banner_enabled = cleaned_data.get('banner_enabled')
        banner_image = cleaned_data.get('banner_image')
        banner_target_url = cleaned_data.get('banner_target_url')
        
        # Validate that melee_format is provided when is_melee is True
        if is_melee and not melee_format:
            raise forms.ValidationError("Mêlée format must be specified when Mêlée mode is enabled.")
            
        # Clear melee_format when is_melee is False
        if not is_melee:
            cleaned_data['melee_format'] = None
            
        # Banner validation
        if banner_enabled:
            if not banner_image:
                raise forms.ValidationError("Banner image is required when banner is enabled.")
            if not banner_target_url:
                raise forms.ValidationError("Banner target URL is required when banner is enabled.")
            
            # Validate banner image size (max 2MB)
            if banner_image and hasattr(banner_image, 'size') and banner_image.size > 2 * 1024 * 1024:
                raise forms.ValidationError("Banner image must be smaller than 2MB.")
                
            # Validate banner target URL format
            if banner_target_url and not (banner_target_url.startswith('http://') or banner_target_url.startswith('https://')):
                raise forms.ValidationError("Banner target URL must start with http:// or https://")
            
        return cleaned_data


class StageForm(forms.ModelForm):
    """Form for creating and editing tournament stages with Incomplete Round Robin support"""
    
    class Meta:
        model = Stage
        fields = [
            'tournament', 'stage_number', 'name', 'format',
            'num_rounds_in_stage', 'num_qualifiers', 'num_matches_per_team'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'e.g., Qualification Round, Semi-Finals'}),
            'num_matches_per_team': forms.NumberInput(attrs={
                'min': '1',
                'placeholder': 'Leave blank for full Round Robin'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Add help text for num_matches_per_team
        self.fields['num_matches_per_team'].help_text = (
            "For Round Robin stages only: Number of matches each team should play. "
            "Leave blank for full Round Robin (every team plays every other team). "
            "Use this for Incomplete Round Robin to limit matches with large tournaments."
        )
        
        # Make num_matches_per_team conditional
        self.fields['num_matches_per_team'].required = False

    def clean(self):
        cleaned_data = super().clean()
        
        format_type = cleaned_data.get('format')
        num_matches_per_team = cleaned_data.get('num_matches_per_team')
        tournament = cleaned_data.get('tournament')
        
        # Validate num_matches_per_team only applies to Round Robin
        if num_matches_per_team and format_type != 'round_robin':
            raise ValidationError({
                'num_matches_per_team': 
                "Number of matches per team can only be specified for Round Robin stages."
            })
        
        # Validate num_matches_per_team is reasonable
        if num_matches_per_team and tournament:
            # Get number of teams in tournament (estimate)
            team_count = tournament.teams.count()
            
            if team_count > 0:
                max_matches = team_count - 1  # Maximum possible matches per team in Round Robin
                
                if num_matches_per_team >= max_matches:
                    raise ValidationError({
                        'num_matches_per_team': 
                        f"Number of matches per team ({num_matches_per_team}) must be less than "
                        f"the number of teams minus 1 ({max_matches}). "
                        f"For full Round Robin, leave this field blank."
                    })
                
                if num_matches_per_team < 1:
                    raise ValidationError({
                        'num_matches_per_team': 
                        "Number of matches per team must be at least 1."
                    })
        
        # Validate stage number is unique within tournament
        stage_number = cleaned_data.get('stage_number')
        if tournament and stage_number:
            existing_stages = Stage.objects.filter(
                tournament=tournament, 
                stage_number=stage_number
            )
            
            # Exclude current instance if editing
            if self.instance and self.instance.pk:
                existing_stages = existing_stages.exclude(pk=self.instance.pk)
            
            if existing_stages.exists():
                raise ValidationError({
                    'stage_number': 
                    f"Stage number {stage_number} already exists for this tournament."
                })
        
        return cleaned_data


class TeamAssignmentForm(forms.Form):
    """Form for assigning teams to a tournament"""
    teams = forms.ModelMultipleChoiceField(
        queryset=Team.objects.all(),
        widget=forms.CheckboxSelectMultiple,
        required=False
    )
    
    def __init__(self, tournament, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tournament = tournament
        # Pre-select teams already in the tournament
        initial_teams = Team.objects.filter(tournamentteam__tournament=tournament)
        self.fields["teams"].initial = initial_teams
        # Add seeding position input if needed here
        
    def save(self):
        selected_teams = self.cleaned_data["teams"]
        current_tournament_teams = TournamentTeam.objects.filter(tournament=self.tournament)
        current_teams_dict = {tt.team_id: tt for tt in current_tournament_teams}

        # Remove teams that were unselected
        selected_team_ids = {team.id for team in selected_teams}
        for team_id, tournament_team in current_teams_dict.items():
            if team_id not in selected_team_ids:
                tournament_team.delete()
        
        # Add newly selected teams or update existing
        for team in selected_teams:
            if team.id not in current_teams_dict:
                TournamentTeam.objects.create(tournament=self.tournament, team=team)
            # Update seeding or other fields if added to the form
                
        return self.tournament


class MeleePlayerRegistrationForm(forms.Form):
    """Form for individual player registration in Mêlée tournaments"""
    player_codename = forms.CharField(
        max_length=6,
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "Enter your codename",
            "autocomplete": "off",
            "maxlength": "6"
        }),
        help_text="Enter your 6-character secret codename"
    )
    
    def __init__(self, tournament, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tournament = tournament
        
        # Validate that this is a Mêlée tournament
        if not tournament.is_melee:
            raise forms.ValidationError("This tournament is not configured for Mêlée mode.")
    
    def clean_player_codename(self):
        codename = self.cleaned_data['player_codename'].upper()
        
        # Find player by codename using PlayerCodename model
        from friendly_games.models import PlayerCodename
        try:
            player_codename = PlayerCodename.objects.get(codename=codename)
            player = player_codename.player
        except PlayerCodename.DoesNotExist:
            raise forms.ValidationError("Invalid codename. Please check your codename and try again.")
        
        # Check if player is already registered for this tournament
        from .models import MeleePlayer
        if MeleePlayer.objects.filter(tournament=self.tournament, player=player).exists():
            raise forms.ValidationError("You are already registered for this tournament.")
        
        # Check registration limit
        if self.tournament.max_participants:
            current_registrations = MeleePlayer.objects.filter(tournament=self.tournament).count()
            if current_registrations >= self.tournament.max_participants:
                raise forms.ValidationError(
                    f"Tournament is full! Maximum {self.tournament.max_participants} players allowed."
                )
        
        # Store the player object for use in save method
        self.player = player
        return codename
    
    def save(self):
        """Register the player for the Mêlée tournament"""
        from .models import MeleePlayer
        
        melee_player = MeleePlayer.objects.create(
            tournament=self.tournament,
            player=self.player,
            original_team=self.player.team  # Store original team for restoration
        )
        
        return melee_player


class IncompleteRoundRobinConfigForm(forms.Form):
    """Form for configuring Incomplete Round Robin parameters"""
    
    num_matches_per_team = forms.IntegerField(
        min_value=1,
        label="Matches per Team",
        help_text="Number of matches each team should play in this Round Robin stage",
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'e.g., 3'
        })
    )
    
    def __init__(self, *args, **kwargs):
        self.tournament = kwargs.pop('tournament', None)
        super().__init__(*args, **kwargs)
        
        # Set dynamic validation based on tournament
        if self.tournament:
            team_count = self.tournament.teams.count()
            if team_count > 0:
                max_matches = team_count - 1
                self.fields['num_matches_per_team'].widget.attrs['max'] = max_matches - 1
                self.fields['num_matches_per_team'].help_text += (
                    f" (Maximum: {max_matches - 1} for {team_count} teams)"
                )

    def clean_num_matches_per_team(self):
        num_matches = self.cleaned_data['num_matches_per_team']
        
        if self.tournament:
            team_count = self.tournament.teams.count()
            if team_count > 0:
                max_matches = team_count - 1
                
                if num_matches >= max_matches:
                    raise ValidationError(
                        f"Number of matches per team must be less than {max_matches} "
                        f"for {team_count} teams. Use full Round Robin instead."
                    )
        
        return num_matches