from django import forms
from teams.models import Team
from tournaments.models import Tournament
from .models import TeamTournamentSignin

class TournamentSigninForm(forms.Form):
    """Form for teams to sign in to tournaments using their PIN"""
    tournament = forms.ModelChoiceField(
        queryset=Tournament.objects.filter(is_active=True, is_archived=False),
        empty_label="Select a tournament",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    team = forms.ModelChoiceField(
        queryset=Team.objects.all(),
        empty_label="Select your team",
        widget=forms.Select(attrs={'class': 'form-select'})
    )
    pin = forms.CharField(
        max_length=6, 
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Enter your 6-digit PIN'})
    )
    
    def clean(self):
        cleaned_data = super().clean()
        team = cleaned_data.get('team')
        pin = cleaned_data.get('pin')
        tournament = cleaned_data.get('tournament')
        
        if team and pin and tournament:
            # Verify PIN - only the team's PIN is needed, no other team verification
            if pin != team.pin:
                raise forms.ValidationError("Invalid PIN. Please try again.")
            
            # Check if team is already signed in to this tournament
            existing_signin = TeamTournamentSignin.objects.filter(
                team=team,
                tournament=tournament,
                is_active=True
            ).exists()
            
            if existing_signin:
                # This is not an error, just information
                self.signin_exists = True
            else:
                self.signin_exists = False
                
        return cleaned_data
