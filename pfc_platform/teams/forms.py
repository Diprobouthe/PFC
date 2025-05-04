from django import forms
from .models import Team, Player, TeamAvailability

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
