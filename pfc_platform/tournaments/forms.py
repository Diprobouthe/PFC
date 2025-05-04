from django import forms
from .models import Tournament, TournamentTeam
from teams.models import Team

class TournamentForm(forms.ModelForm):
    """Form for creating and editing tournaments"""
    class Meta:
        model = Tournament
        # Remove number_of_rounds as it was removed from the model
        fields = [
            "name", "description", "format", 
            "has_triplets", "has_doublets", "has_tete_a_tete", # Use these instead of play_format directly
            "start_date", "end_date"
        ]
        widgets = {
            "start_date": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "end_date": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "description": forms.Textarea(attrs={"rows": 4}),
            # Use CheckboxSelectMultiple for boolean fields if desired
            # "has_triplets": forms.CheckboxInput(), 
            # "has_doublets": forms.CheckboxInput(),
            # "has_tete_a_tete": forms.CheckboxInput(),
        }
        # Ensure play_format is set automatically in the model's save method

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

