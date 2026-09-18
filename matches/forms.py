from django import forms
from .models import Match, MatchResult
from teams.models import Player


def _get_team_players_for_match(match, team):
    """
    Return the correct Player queryset for a team in the context of a specific match.

    P3 precedence for Mêlée is MatchPlayer snapshot, then the exact
    Tournament/Round MeleeRoundAssignment, then the legacy Player.team
    compatibility fallback. Non-Mêlée behavior remains Player.team based.

    The function always returns a *queryset* (not a list) so it can be assigned
    directly to a ModelMultipleChoiceField.queryset.
    """
    from .melee_roster_resolution import players_for_match_team

    return players_for_match_team(match, team)


class MatchActivationForm(forms.Form):
    """Form for activating a match using team PIN"""
    pin = forms.CharField(
        max_length=6,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control team-pin-field',
            'placeholder': 'Enter your team PIN',
            'autocomplete': 'off'
        }),
        label="Team PIN"
    )
    players = forms.ModelMultipleChoiceField(
        queryset=Player.objects.none(),
        widget=forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        required=True
    )

    def __init__(self, match, team, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.match = match
        self.team = team

        # Build the correct player queryset for this team/match combination.
        player_qs = _get_team_players_for_match(match, team)
        self.fields["players"].queryset = player_qs

        # Add player role fields dynamically for every player in the queryset.
        for player in player_qs:
            field_name = f"role_{player.id}"
            self.fields[field_name] = forms.ChoiceField(
                choices=[
                    ('pointer', 'Pointer'),
                    ('milieu', 'Milieu'),
                    ('tirer', 'Shooter'),
                    ('flex', 'Flex')
                ],
                required=False,
                widget=forms.RadioSelect(attrs={"class": "role-radio"}),
                initial="flex"
            )

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

    def clean(self):
        cleaned_data = super().clean()
        # Role fields are optional; they default to "flex" in the view.
        return cleaned_data


class MatchResultForm(forms.ModelForm):
    """Form for submitting match results"""
    team1_score = forms.IntegerField(min_value=0, max_value=13)
    team2_score = forms.IntegerField(min_value=0, max_value=13)
    pin = forms.CharField(
        max_length=6,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control team-pin-field',
            'placeholder': 'Enter your team PIN',
            'autocomplete': 'off'
        }),
        label="Your Team PIN to Submit"
    )

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
        return cleaned_data


class MatchValidationForm(forms.Form):
    """Form for validating or disagreeing with match results"""
    validation_action = forms.ChoiceField(
        choices=[("agree", "Agree with submitted score"), ("disagree", "Disagree with submitted score")],
        widget=forms.RadioSelect,
        required=True,
        label="Validate Score:"
    )
    pin = forms.CharField(
        max_length=6,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control team-pin-field',
            'placeholder': 'Enter your team PIN',
            'autocomplete': 'off'
        }),
        label="Your Team PIN to Confirm"
    )

    def __init__(self, match, validating_team, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.match = match
        self.validating_team = validating_team

    def clean_pin(self):
        pin = self.cleaned_data.get("pin")
        if pin != self.validating_team.pin:
            raise forms.ValidationError("Invalid PIN. Please try again.")
        return pin
