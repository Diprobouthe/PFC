from django import forms
from .models import Team, Player, TeamAvailability, PlayerProfile, TeamProfile, SubTeam, SubTeamPlayerAssignment

class TeamForm(forms.ModelForm):
    """Form for creating and editing teams"""
    class Meta:
        model = Team
        fields = ['name']
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If this is an existing team, don't allow PIN to be changed
        if self.instance and self.instance.pk:
            self.fields.pop('pin', None)

class PlayerForm(forms.ModelForm):
    """Form for creating and editing players"""
    class Meta:
        model = Player
        fields = ['name', 'is_captain']
        
class TeamAvailabilityForm(forms.ModelForm):
    """Form for setting team availability"""
    class Meta:
        model = TeamAvailability
        fields = ['available_from', 'available_to', 'notes']
        widgets = {
            'available_from': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'available_to': forms.DateTimeInput(attrs={'type': 'datetime-local'}),
            'notes': forms.Textarea(attrs={'rows': 3}),
        }

class TeamPinVerificationForm(forms.Form):
    """Form for verifying team PIN"""
    pin = forms.CharField(max_length=6, widget=forms.PasswordInput())
    
    def __init__(self, team, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.team = team
        
    def clean_pin(self):
        pin = self.cleaned_data.get('pin')
        if pin != self.team.pin:
            raise forms.ValidationError("Invalid PIN. Please try again.")
        return pin


class PublicPlayerForm(forms.Form):
    """Form for public player registration with team affiliation options"""
    
    TEAM_CHOICE_OPTIONS = [
        ('friendly', 'Join Friendly Games (Default)'),
        ('existing', 'Join Existing Team with PIN'),
        ('new', 'Create New Team'),
    ]
    
    name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={
            'placeholder': 'Enter your full name',
            'class': 'form-control'
        }),
        help_text="Your display name for matches and leaderboards"
    )
    
    codename = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={
            'placeholder': 'Enter 6-character codename',
            'class': 'form-control',
            'style': 'text-transform: uppercase;'
        }),
        help_text="Unique 6-character identifier for login"
    )
    
    profile_picture = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': 'image/*'
        }),
        help_text="Upload a profile photo (optional)"
    )
    
    team_choice = forms.ChoiceField(
        choices=TEAM_CHOICE_OPTIONS,
        initial='friendly',
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        help_text="Choose how you want to join or create a team"
    )
    
    # Team search field (replaces dropdown)
    team_search = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Search for a team by name...',
            'class': 'form-control',
            'autocomplete': 'off',
            'id': 'team-search-input'
        }),
        help_text="Type to search for teams"
    )
    
    # Hidden field to store selected team ID
    selected_team_id = forms.CharField(
        max_length=10,
        required=False,
        widget=forms.HiddenInput(attrs={'id': 'selected-team-id'})
    )
    
    team_pin = forms.CharField(
        max_length=6,
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Enter team PIN',
            'class': 'form-control'
        }),
        help_text="Enter the PIN for the selected team"
    )
    
    def clean_codename(self):
        """Validate codename uniqueness and format"""
        codename = self.cleaned_data.get('codename', '').upper()
        
        # Check if codename already exists in Player.name field (where codenames are stored)
        # Only check against players that were created through the public registration
        # (these have codenames in the name field)
        existing_codenames = Player.objects.filter(
            name__iexact=codename,
            name__regex=r'^[A-Z0-9]{6}$'  # Only check 6-character alphanumeric names (codenames)
        )
        
        if existing_codenames.exists():
            raise forms.ValidationError("This codename is already taken. Please choose another.")
        
        return codename
    
    def clean(self):
        """Validate team selection and PIN combination"""
        cleaned_data = super().clean()
        team_choice = cleaned_data.get('team_choice')
        selected_team_id = cleaned_data.get('selected_team_id')
        team_pin = cleaned_data.get('team_pin')
        
        if team_choice == 'existing':
            if not selected_team_id:
                raise forms.ValidationError("Please search for and select a team to join.")
            
            try:
                selected_team = Team.objects.get(id=selected_team_id)
                cleaned_data['existing_team'] = selected_team
            except Team.DoesNotExist:
                raise forms.ValidationError("Selected team not found. Please search again.")
            
            if not team_pin:
                raise forms.ValidationError("Please enter the team PIN.")
            
            # Validate that the PIN matches the selected team
            if selected_team.pin != team_pin:
                raise forms.ValidationError(f"Invalid PIN for team '{selected_team.name}'. Please check and try again.")
        
        return cleaned_data


class TeamProfileForm(forms.ModelForm):
    """Form for editing team profiles"""
    class Meta:
        model = TeamProfile
        fields = [
            'logo_svg', 'team_photo_jpg', 'description', 'motto', 
            'founded_date', 'profile_type'
        ]
        widgets = {
            'logo_svg': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': '.svg',
                'help_text': 'Upload team logo in SVG format'
            }),
            'team_photo_jpg': forms.FileInput(attrs={
                'class': 'form-control',
                'accept': 'image/jpeg,image/jpg',
                'help_text': 'Upload team photo in JPG format'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Tell us about your team...'
            }),
            'motto': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Team motto or slogan'
            }),
            'founded_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date'
            }),
            'profile_type': forms.Select(attrs={
                'class': 'form-control'
            })
        }
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Customize field labels and help text
        self.fields['logo_svg'].label = 'Team Logo (SVG)'
        self.fields['logo_svg'].help_text = 'Upload your team logo in SVG format for best quality'
        
        self.fields['team_photo_jpg'].label = 'Team Photo (JPG)'
        self.fields['team_photo_jpg'].help_text = 'Upload a team photo in JPG format'
        
        self.fields['description'].label = 'Team Description'
        self.fields['description'].help_text = 'Describe your team, history, or achievements'
        
        self.fields['motto'].label = 'Team Motto'
        self.fields['motto'].help_text = 'Your team\'s motto or slogan'
        
        self.fields['founded_date'].label = 'Founded Date'
        self.fields['founded_date'].help_text = 'When was your team founded?'
        
        self.fields['profile_type'].label = 'Profile Type'
        self.fields['profile_type'].help_text = 'Type of team profile'
        
        # Hide profile_type for regular teams (auto-set to 'full')
        self.fields['profile_type'].widget = forms.HiddenInput()
        
    def clean_logo_svg(self):
        """Validate SVG file upload"""
        logo = self.cleaned_data.get('logo_svg')
        if logo:
            if not logo.name.lower().endswith('.svg'):
                raise forms.ValidationError('Please upload a valid SVG file.')
            
            # Check file size (max 2MB)
            if logo.size > 2 * 1024 * 1024:
                raise forms.ValidationError('SVG file size must be less than 2MB.')
        
        return logo
    
    def clean_team_photo_jpg(self):
        """Validate JPG file upload"""
        photo = self.cleaned_data.get('team_photo_jpg')
        if photo:
            if not photo.name.lower().endswith(('.jpg', '.jpeg')):
                raise forms.ValidationError('Please upload a valid JPG file.')
            
            # Check file size (max 5MB)
            if photo.size > 5 * 1024 * 1024:
                raise forms.ValidationError('Photo file size must be less than 5MB.')
        
        return photo

class TeamBadgeForm(forms.Form):
    """Form for adding badges to teams"""
    BADGE_CHOICES = [
        ('tournament_winner', 'Tournament Winner'),
        ('tournament_participant', 'Tournament Participant'),
        ('friendly_champion', 'Friendly Games Champion'),
        ('team_spirit', 'Team Spirit Award'),
        ('most_improved', 'Most Improved Team'),
        ('veteran_team', 'Veteran Team (5+ years)'),
        ('rookie_team', 'Rookie Team'),
        ('community_favorite', 'Community Favorite'),
        ('fair_play', 'Fair Play Award'),
        ('custom', 'Custom Badge'),
    ]
    
    badge_type = forms.ChoiceField(
        choices=BADGE_CHOICES,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label='Badge Type'
    )
    
    custom_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter custom badge name'
        }),
        label='Custom Badge Name',
        help_text='Required if "Custom Badge" is selected'
    )
    
    description = forms.CharField(
        max_length=200,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Badge description or achievement details'
        }),
        label='Description',
        help_text='Optional description of the achievement'
    )
    
    def clean(self):
        cleaned_data = super().clean()
        badge_type = cleaned_data.get('badge_type')
        custom_name = cleaned_data.get('custom_name')
        
        if badge_type == 'custom' and not custom_name:
            raise forms.ValidationError('Custom badge name is required when selecting "Custom Badge".')
        
        return cleaned_data


# ===== TEAM MANAGEMENT FORMS =====

class SubTeamForm(forms.ModelForm):
    """Form for creating and editing sub-teams"""
    
    class Meta:
        model = SubTeam
        fields = ['name', 'sub_team_type', 'max_players']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., Triplet A, Doublette 1'
            }),
            'sub_team_type': forms.Select(attrs={
                'class': 'form-select'
            }),
            'max_players': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1,
                'max': 10
            })
        }
        help_texts = {
            'name': 'Choose a unique name for this sub-team',
            'sub_team_type': 'Select the formation type',
            'max_players': 'Maximum number of players (1-10)'
        }
    
    def __init__(self, *args, **kwargs):
        self.parent_team = kwargs.pop('parent_team', None)
        super().__init__(*args, **kwargs)
        
        # Auto-set max_players based on sub_team_type
        self.fields['sub_team_type'].widget.attrs.update({
            'onchange': 'updateMaxPlayers(this.value)'
        })
    
    def clean_name(self):
        name = self.cleaned_data['name']
        if self.parent_team:
            # Check for duplicate names within the same parent team
            existing = SubTeam.objects.filter(
                parent_team=self.parent_team,
                name=name
            )
            if self.instance.pk:
                existing = existing.exclude(pk=self.instance.pk)
            
            if existing.exists():
                raise forms.ValidationError(
                    f"A sub-team named '{name}' already exists in {self.parent_team.name}"
                )
        return name
    
    def clean(self):
        cleaned_data = super().clean()
        sub_team_type = cleaned_data.get('sub_team_type')
        max_players = cleaned_data.get('max_players')
        
        # Auto-adjust max_players based on type
        if sub_team_type and not max_players:
            type_defaults = {
                'triplet': 3,
                'doublette': 2,
                'tete_a_tete': 1,
                'custom': 3
            }
            cleaned_data['max_players'] = type_defaults.get(sub_team_type, 3)
        
        return cleaned_data


class PlayerRecruitmentForm(forms.Form):
    """Form for recruiting players from Friendly Team"""
    
    player = forms.ModelChoiceField(
        queryset=Player.objects.none(),
        widget=forms.Select(attrs={
            'class': 'form-select'
        }),
        help_text='Select a player from the Friendly Team to recruit'
    )
    
    def __init__(self, *args, **kwargs):
        self.team = kwargs.pop('team', None)
        super().__init__(*args, **kwargs)
        
        if self.team:
            # Only show players from Friendly Team
            available_players = self.team.get_available_players_for_recruitment()
            self.fields['player'].queryset = available_players
            
            if not available_players.exists():
                self.fields['player'].help_text = 'No players available for recruitment from Friendly Team'
                self.fields['player'].widget.attrs['disabled'] = True


class PlayerReleaseForm(forms.Form):
    """Form for releasing players back to Friendly Team"""
    
    player = forms.ModelChoiceField(
        queryset=Player.objects.none(),
        widget=forms.Select(attrs={
            'class': 'form-select'
        }),
        help_text='Select a player to release back to Friendly Team'
    )
    
    confirm_release = forms.BooleanField(
        required=True,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        help_text='I confirm that I want to release this player'
    )
    
    def __init__(self, *args, **kwargs):
        self.team = kwargs.pop('team', None)
        super().__init__(*args, **kwargs)
        
        if self.team:
            # Only show players from this team
            self.fields['player'].queryset = self.team.get_main_roster()


class SubTeamPlayerAssignmentForm(forms.Form):
    """Form for assigning players to sub-teams"""
    
    player = forms.ModelChoiceField(
        queryset=Player.objects.none(),
        widget=forms.Select(attrs={
            'class': 'form-select'
        }),
        help_text='Select a player from your team roster'
    )
    
    position = forms.ChoiceField(
        choices=[
            ('any', 'Any Position'),
            ('tirer', 'Tireur'),
            ('pointeur', 'Pointeur'),
            ('milieu', 'Milieu'),
        ],
        initial='any',
        widget=forms.Select(attrs={
            'class': 'form-select'
        }),
        help_text='Select the player\'s position in this sub-team'
    )
    
    def __init__(self, *args, **kwargs):
        self.sub_team = kwargs.pop('sub_team', None)
        super().__init__(*args, **kwargs)
        
        if self.sub_team:
            # Only show unassigned players from parent team
            parent_team = self.sub_team.parent_team
            assigned_player_ids = SubTeamPlayerAssignment.objects.filter(
                sub_team__parent_team=parent_team
            ).values_list('player_id', flat=True)
            
            available_players = parent_team.players.exclude(id__in=assigned_player_ids)
            self.fields['player'].queryset = available_players
            
            if not available_players.exists():
                self.fields['player'].help_text = 'No unassigned players available'
                self.fields['player'].widget.attrs['disabled'] = True
    
    def clean(self):
        cleaned_data = super().clean()
        player = cleaned_data.get('player')
        
        if self.sub_team and player:
            # Check if sub-team is full
            if self.sub_team.is_full():
                raise forms.ValidationError(
                    f"Sub-team {self.sub_team.name} is already full "
                    f"({self.sub_team.max_players} players maximum)"
                )
            
            # Check if player is already assigned to another sub-team
            existing_assignment = SubTeamPlayerAssignment.objects.filter(
                player=player,
                sub_team__parent_team=self.sub_team.parent_team
            ).first()
            
            if existing_assignment:
                raise forms.ValidationError(
                    f"Player {player.name} is already assigned to "
                    f"{existing_assignment.sub_team.name}"
                )
        
        return cleaned_data


class SubTeamPlayerRemovalForm(forms.Form):
    """Form for removing players from sub-teams"""
    
    assignment = forms.ModelChoiceField(
        queryset=SubTeamPlayerAssignment.objects.none(),
        widget=forms.Select(attrs={
            'class': 'form-select'
        }),
        help_text='Select a player assignment to remove'
    )
    
    def __init__(self, *args, **kwargs):
        self.sub_team = kwargs.pop('sub_team', None)
        super().__init__(*args, **kwargs)
        
        if self.sub_team:
            self.fields['assignment'].queryset = self.sub_team.player_assignments.all()
            
            if not self.sub_team.player_assignments.exists():
                self.fields['assignment'].help_text = 'No players assigned to this sub-team'
                self.fields['assignment'].widget.attrs['disabled'] = True

