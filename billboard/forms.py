from django import forms
from django.core.exceptions import ValidationError
from .models import BillboardEntry, BillboardResponse, BillboardSettings
from courts.models import CourtComplex
from teams.models import Player, Team
from pfc_core.session_utils import CodenameSessionManager


class CodenameValidationMixin:
    """Mixin to validate codenames and integrate with session authentication"""
    
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)
        
        # Auto-fill codename if user is logged in
        if self.request and CodenameSessionManager.is_logged_in(self.request):
            logged_in_codename = CodenameSessionManager.get_logged_in_codename(self.request)
            if 'codename' in self.fields and not self.initial.get('codename'):
                self.initial['codename'] = logged_in_codename
                self.fields['codename'].widget.attrs.update({
                    'class': 'form-control is-valid',
                    'readonly': True,
                    'title': f'Auto-filled from session: {logged_in_codename}'
                })
    
    def clean_codename(self):
        codename = self.cleaned_data.get('codename', '').upper()
        if not codename:
            raise ValidationError("Codename is required.")
        
        # Validate format using session manager
        if not CodenameSessionManager.is_valid_codename(codename):
            raise ValidationError("Codename must be exactly 6 alphanumeric characters.")
        
        return codename


class BillboardEntryForm(CodenameValidationMixin, forms.ModelForm):
    # Add team search fields for PFC matches
    team_search = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search for opponent team...',
            'autocomplete': 'off'
        }),
        help_text="Search and select the opponent team"
    )
    
    selected_team_id = forms.CharField(
        max_length=10,
        required=False,
        widget=forms.HiddenInput()
    )
    
    class Meta:
        model = BillboardEntry
        fields = ['codename', 'action_type', 'court_complex', 'scheduled_time', 'scheduled_date', 'opponent_team', 'message']
        widgets = {
            'codename': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter your 6-character codename',
                'maxlength': 6,
                'style': 'text-transform: uppercase;'
            }),
            'action_type': forms.Select(attrs={'class': 'form-select'}),
            'court_complex': forms.Select(attrs={'class': 'form-select'}),
            'scheduled_time': forms.Select(attrs={'class': 'form-select'}),
            'scheduled_date': forms.DateInput(attrs={
                'class': 'form-control',
                'type': 'date',
                'min': '',  # Will be set in __init__
            }),
            'opponent_team': forms.HiddenInput(),  # Hidden, will be populated from team search
            'message': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Optional message...'
            }),
        }
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Set minimum date to today
        from django.utils import timezone
        today = timezone.now().date()
        self.fields['scheduled_date'].widget.attrs['min'] = today.strftime('%Y-%m-%d')
        
        # Make court_complex required
        self.fields['court_complex'].required = True
        self.fields['court_complex'].empty_label = "Select a court complex"
        
        # Set up conditional fields
        self.fields['scheduled_time'].required = False
        self.fields['scheduled_date'].required = False
        self.fields['opponent_team'].required = False
        
        # Add help text
        self.fields['codename'].help_text = "Your 6-character player codename"
        self.fields['scheduled_time'].help_text = "Required for 'going to courts' and 'tournament match' entries"
        self.fields['scheduled_date'].help_text = "Required for scheduled appointments"
    
    def clean(self):
        cleaned_data = super().clean()
        action_type = cleaned_data.get('action_type')
        scheduled_time = cleaned_data.get('scheduled_time')
        scheduled_date = cleaned_data.get('scheduled_date')
        selected_team_id = cleaned_data.get('selected_team_id')
        team_search = cleaned_data.get('team_search')
        codename = cleaned_data.get('codename')
        
        # Validate required fields based on action type
        if action_type == 'GOING_TO_COURTS':
            if not scheduled_time:
                raise ValidationError("Time selection is required for 'going to courts' entries.")
            if not scheduled_date:
                raise ValidationError("Date selection is required for 'going to courts' entries.")
        
        if action_type == 'LOOKING_FOR_MATCH':
            if not scheduled_time:
                raise ValidationError("Time selection is required for tournament match appointments.")
            if not scheduled_date:
                raise ValidationError("Date selection is required for tournament match appointments.")
            
            if not selected_team_id:
                raise ValidationError("Please search and select an opponent team.")
            
            # Validate selected team exists
            try:
                team = Team.objects.get(id=selected_team_id)
                cleaned_data['opponent_team'] = team.name
            except Team.DoesNotExist:
                raise ValidationError("Selected team is invalid.")
        
        # Check daily limits
        if codename and action_type:
            if not BillboardEntry.can_create_entry(codename, action_type):
                settings = BillboardSettings.get_settings()
                raise ValidationError(
                    f"You can only create {settings.max_entries_per_day} entries of this type per day."
                )
        
        return cleaned_data


class BillboardResponseForm(forms.ModelForm, CodenameValidationMixin):
    # Add team PIN verification for PFC match responses
    team_pin = forms.CharField(
        max_length=6,
        required=False,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Enter your team PIN',
            'maxlength': 6,
            'style': 'text-transform: uppercase;'
        }),
        help_text="Required for tournament match responses"
    )
    
    class Meta:
        model = BillboardResponse
        fields = ['codename', 'team_pin']
        widgets = {
            'codename': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Enter your codename',
                'maxlength': 6,
                'style': 'text-transform: uppercase;'
            }),
        }
    
    def __init__(self, *args, entry=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.entry = entry
        self.fields['codename'].help_text = "Your 6-character player codename"
        
        # Make team PIN required for tournament match responses
        if entry and entry.action_type == 'LOOKING_FOR_MATCH':
            self.fields['team_pin'].required = True
    
    def clean(self):
        cleaned_data = super().clean()
        codename = cleaned_data.get('codename', '').upper()
        team_pin = cleaned_data.get('team_pin', '').upper()
        
        if not codename:
            raise ValidationError("Codename is required.")
        
        # For now, just validate format - 6 characters
        if len(codename) != 6:
            raise ValidationError("Codename must be exactly 6 characters.")
        
        if self.entry:
            # Check if user already responded
            if BillboardResponse.objects.filter(entry=self.entry, codename=codename).exists():
                raise ValidationError("You have already responded to this entry.")
            
            # Prevent self-response
            if codename == self.entry.codename:
                raise ValidationError("You cannot respond to your own entry.")
            
            # Special validation for tournament match responses
            if self.entry.action_type == 'LOOKING_FOR_MATCH':
                if not team_pin:
                    raise ValidationError("Team PIN is required to accept tournament match appointments.")
                
                if len(team_pin) != 6:
                    raise ValidationError("Team PIN must be exactly 6 characters.")
                
                # Verify team PIN against the opponent team
                try:
                    from teams.models import Team
                    opponent_team = Team.objects.get(name=self.entry.opponent_team)
                    if opponent_team.pin != team_pin:
                        raise ValidationError("Invalid team PIN. Only the specified opponent team can accept this match.")
                except Team.DoesNotExist:
                    raise ValidationError("Opponent team not found.")
            
            # Check if user can respond to this entry (for other types)
            elif not self.entry.can_respond(codename):
                raise ValidationError("You cannot respond to this entry.")
        
        return cleaned_data


class QuickResponseForm(forms.Form, CodenameValidationMixin):
    """Simple form for AJAX responses with authentication integration"""
    codename = forms.CharField(
        max_length=6,
        widget=forms.TextInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Codename',
            'style': 'text-transform: uppercase;'
        })
    )
    
    def __init__(self, *args, entry=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.entry = entry
    
    def clean_codename(self):
        codename = self.cleaned_data.get('codename', '').upper()
        
        if not codename:
            raise ValidationError("Codename is required.")
        
        # For now, just validate format - 6 characters
        if len(codename) != 6:
            raise ValidationError("Invalid codename.")
        
        if self.entry:
            # Check if user already responded
            if BillboardResponse.objects.filter(entry=self.entry, codename=codename).exists():
                raise ValidationError("Already responded.")
            
            # Check if user can respond
            if not self.entry.can_respond(codename):
                raise ValidationError("Cannot respond to this entry.")
            
            # Prevent self-response
            if codename == self.entry.codename:
                raise ValidationError("Cannot respond to own entry.")
        
        return codename

