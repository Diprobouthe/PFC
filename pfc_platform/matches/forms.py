from django import forms
from .models import Match, MatchResult
from teams.models import Player

class MatchActivationForm(forms.Form):
    """Form for activating a match using team PIN"""
    pin = forms.CharField(max_length=6, widget=forms.PasswordInput())
    players = forms.ModelMultipleChoiceField(
        queryset=Player.objects.none(),
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        required=True
    )

    def __init__(self, match, team, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.match = match
        self.team = team

        # Set the queryset to only include players from this team
        self.fields["players"].queryset = Player.objects.filter(team=team)

    def clean_pin(self):
        pin = self.cleaned_data.get("pin")
        if pin != self.team.pin:
            raise forms.ValidationError("Invalid PIN. Please try again.")
        return pin

    def clean_players(self):
        players = self.cleaned_data.get("players")
        if not players or len(players) < 1:
            raise forms.ValidationError("You must select at least one player.")
        return players

class MatchResultForm(forms.ModelForm):
    """Form for submitting match results"""
    team1_score = forms.IntegerField(min_value=0, max_value=13)
    team2_score = forms.IntegerField(min_value=0, max_value=13)
    pin = forms.CharField(max_length=6, widget=forms.PasswordInput(), label="Your Team PIN to Submit")

    class Meta:
        model = MatchResult
        fields = ["photo_evidence", "notes"]

    def __init__(self, match, submitting_team, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.match = match
        self.submitting_team = submitting_team

        # Pre-populate with existing scores if available
        if match.team1_score is not None:
            self.fields["team1_score"].initial = match.team1_score
        if match.team2_score is not None:
            self.fields["team2_score"].initial = match.team2_score

    def clean_pin(self):
        pin = self.cleaned_data.get("pin")
        if pin != self.submitting_team.pin:
            raise forms.ValidationError("Invalid PIN. Please try again.")
        return pin

    def clean(self):
        cleaned_data = super().clean()
        score1 = cleaned_data.get("team1_score")
        score2 = cleaned_data.get("team2_score")

        if score1 is not None and score2 is not None:
            if score1 == score2:
                raise forms.ValidationError("Scores cannot be equal. One team must win.")
            # Temporarily commented out strict 13-point validation to allow submission
            # if not ((score1 == 13 and 0 <= score2 < 13) or (score2 == 13 and 0 <= score1 < 13)):
            #      raise forms.ValidationError("Invalid score combination. One score must be 13 and the other less than 13.")
        return cleaned_data

class MatchValidationForm(forms.Form):
    """Form for validating or disagreeing with match results"""
    validation_action = forms.ChoiceField(
        choices=[("agree", "Agree with submitted score"), ("disagree", "Disagree with submitted score")],
        widget=forms.RadioSelect,
        required=True,
        label="Validate Score:"
    )
    pin = forms.CharField(max_length=6, widget=forms.PasswordInput(), label="Your Team PIN to Confirm")

    def __init__(self, match, validating_team, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.match = match
        self.validating_team = validating_team

    def clean_pin(self):
        pin = self.cleaned_data.get("pin")
        if pin != self.validating_team.pin:
            raise forms.ValidationError("Invalid PIN. Please try again.")
        return pin
